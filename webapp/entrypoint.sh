#!/bin/bash
set -e

echo "Waiting for database..."
while ! python -c "
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
conn.close()
" 2>/dev/null; do
    sleep 1
done
echo "Database is ready!"

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Creating superuser if not exists..."
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@acu.edu.tr', 'admin123')
    print('  Superuser created: admin / admin123')
else:
    print('  Superuser already exists')
"

# ── Wait for Ollama and pull required models ──────────────
OLLAMA_URL="${OLLAMA_BASE_URL:-http://ollama:11434}"
LLM="${LLM_MODEL:-qwen2.5:3b}"
EMB="${EMBEDDING_MODEL:-nomic-embed-text}"

echo "Waiting for Ollama at ${OLLAMA_URL}..."
until curl -sf "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; do
    sleep 3
done
echo "Ollama is ready!"

# Pull models only if not already present
pull_if_missing() {
    local model="$1"
    local model_base="${model%%:*}"
    if curl -sf "${OLLAMA_URL}/api/tags" | grep -q "\"${model_base}"; then
        echo "  Model '${model}' already available."
    else
        echo "  Pulling model '${model}'... (this may take several minutes)"
        curl -s -X POST "${OLLAMA_URL}/api/pull" \
            -H "Content-Type: application/json" \
            -d "{\"name\": \"${model}\"}" | tail -1
        echo "  Model '${model}' pulled."
    fi
}

pull_if_missing "${LLM}"
pull_if_missing "${EMB}"

# ── Auto-scrape if database has no content ────────────────
PAGE_COUNT=$(python manage.py shell -c "
from chat.models import WebPage
print(WebPage.objects.count())
" 2>/dev/null || echo "0")

if [ "$PAGE_COUNT" -eq "0" ] 2>/dev/null; then
    echo "No pages in DB. Running initial scrape (this may take a few minutes)..."
    python manage.py scrape_acu --max-pages 80 || echo "ACU scrape failed, continuing..."
    python manage.py scrape_bologna || echo "Bologna scrape failed, continuing..."
    python manage.py generate_embeddings || echo "Embedding generation failed, continuing..."
    echo "Initial data load complete."
else
    echo "Database already has ${PAGE_COUNT} pages. Skipping initial scrape."
fi

echo "Starting Gunicorn server..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --threads 2 \
    --timeout 300 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -
