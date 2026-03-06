#!/bin/bash
set -e

echo "🔄 Waiting for database..."
while ! python -c "
import psycopg2
import os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
conn.close()
" 2>/dev/null; do
    sleep 1
done
echo "✅ Database is ready!"

echo "🔄 Running migrations..."
python manage.py migrate --noinput

echo "🔄 Collecting static files..."
python manage.py collectstatic --noinput

echo "🔄 Creating superuser if not exists..."
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@acu.edu.tr', 'admin123')
    print('  ✅ Superuser created (admin/admin123)')
else:
    print('  ℹ️  Superuser already exists')
"

echo "🚀 Starting Gunicorn server..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --threads 2 \
    --timeout 300 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -
