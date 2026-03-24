# ACU AI Chatbot — Scraping Guide

Complete instructions for scraping both the main ACU website and Bologna system.

## Quick Start

```bash
# Start Docker services
docker-compose up -d

# Wait for services to be ready (30-60 seconds)
docker-compose exec webapp python manage.py migrate --noinput
docker-compose exec webapp python manage.py collectstatic --noinput

# Scrape everything (main + Bologna)
docker-compose exec webapp python manage.py scrape_acu --source=all

# Generate embeddings (automatic during scraping, but can re-run)
docker-compose exec webapp python manage.py generate_embeddings
```

## Detailed Commands

### 1. Scrape Main Site Only (acibadem.edu.tr)
```bash
docker-compose exec webapp python manage.py scrape_acu --source=main
```
- **Time:** ~5-10 minutes
- **Pages:** ~500 (or set with `--max-pages`)
- **Output:** Main university website content (programs, faculty, admission, campus info)

### 2. Scrape Bologna System Only (obs.acibadem.edu.tr)
```bash
docker-compose exec webapp python manage.py scrape_acu --source=bologna
```
- **Time:** ~15-30 minutes (uses Playwright for JavaScript rendering)
- **Pages:** ~200-400 (depends on program count)
- **Output:** Academic Bologna system (courses, curricula, learning outcomes, credits)

### 3. Scrape Everything
```bash
docker-compose exec webapp python manage.py scrape_acu --source=all
```
- **Time:** ~30-45 minutes total
- **Output:** Complete university knowledge base

### 4. Clear & Re-Scrape
```bash
# Clear only main site and re-scrape
docker-compose exec webapp python manage.py scrape_acu --source=main --clear

# Clear only Bologna and re-scrape
docker-compose exec webapp python manage.py scrape_acu --source=bologna --clear

# Clear everything and start fresh
docker-compose exec webapp python manage.py scrape_acu --source=all --clear
```

### 5. Re-Process Existing Pages
```bash
# Re-generate embeddings for already-scraped pages (updates RAG index)
docker-compose exec webapp python manage.py scrape_acu --source=main --reprocess
docker-compose exec webapp python manage.py scrape_acu --source=bologna --reprocess
```

### 6. Adjust Scraping Limits
```bash
# Scrape fewer pages (faster testing)
docker-compose exec webapp python manage.py scrape_acu --source=main --max-pages=50

# Scrape more pages (default 500)
docker-compose exec webapp python manage.py scrape_acu --source=all --max-pages=1000
```

## What Gets Scraped

### Main Site (acibadem.edu.tr)
- University overview and mission
- Faculty and department information
- Academic programs (bachelor's, master's, PhD)
- Admission requirements and application procedures
- Tuition fees and scholarship information
- Campus facilities (cafeteria, library, sports)
- Student clubs and organizations
- News and announcements

**Categories:** faculty, department, program, admission, campus, about, academic, student, contact, research

### Bologna System (obs.acibadem.edu.tr)
- Program curricula and course lists
- Course credits (ECTS) and hours
- Learning outcomes and competencies
- Admission requirements
- Graduation conditions
- Academic staff information
- Program profiles and objectives

**Pages per program:** ~17 (index + 16 sub-pages)

## Monitoring Progress

During scraping, you'll see output like:
```
Progress: 25 pages scraped, 150 URLs in queue
Progress: 50 pages scraped, 120 URLs in queue
...
```

Check database stats anytime:
```bash
docker-compose exec webapp python manage.py shell
>>> from chat.services.rag_service import rag_service
>>> stats = rag_service.get_stats()
>>> print(stats)
```

## Troubleshooting

### "Connection refused" error
```bash
# Check if services are running
docker-compose ps

# If not running, start them
docker-compose up -d

# Wait 30 seconds, then retry
```

### "pgvector extension not available"
```bash
# This is automatically handled in migrations
# If error persists, restart PostgreSQL
docker-compose restart db
docker-compose exec webapp python manage.py migrate
```

### "Playwright browser failed to launch"
```bash
# Ensure Playwright dependencies are installed
docker-compose exec webapp pip install playwright
docker-compose exec webapp python -m playwright install chromium
```

### Low content/empty results
- Main site scraping may need to revisit certain pages
- Bologna scraping depends on JavaScript rendering (Playwright handles this)
- If Bologna fails, the scraper falls back to 100+ known program IDs

### Scraping too slow
```bash
# Reduce delay between requests (default 2s)
# In docker-compose.yml, set SCRAPE_DELAY=1.0
docker-compose exec webapp python manage.py scrape_acu --source=main
```

## Performance Notes

- **Main site:** Sequential BFS crawler with 2s rate limiting per URL
- **Bologna:** Parallel Playwright sessions, ~1.5s per page
- **Database:** Embeddings generated in-process (GPU accelerated if available)

## Verification

After scraping, verify content:
```bash
docker-compose exec webapp python manage.py shell
>>> from chat.models import WebPage, DocumentChunk
>>> WebPage.objects.count()  # Should be 500+
>>> DocumentChunk.objects.count()  # Should be 5000+
>>> WebPage.objects.filter(source='main').count()  # Main site pages
>>> WebPage.objects.filter(source='bologna').count()  # Bologna pages
```

## Local Development (without Docker)

If you need to run locally with system Python:

```bash
# Install dependencies
cd webapp
pip install -r requirements.txt
playwright install chromium

# Ensure PostgreSQL, Redis, Ollama are running separately
python manage.py scrape_acu --source=main
python manage.py scrape_acu --source=bologna
```

## Advanced

### Custom URL delays (rate limiting)
Edit `.env` or set environment variable:
```bash
SCRAPE_DELAY=3.0  # Seconds between requests (default: 2.0)
```

### Increase max pages
```bash
SCRAPE_MAX_PAGES=1000  # Maximum pages to scrape (default: 500)
```

### Environment Variables
```bash
# See webapp/config/settings.py for all options:
SCRAPE_DELAY=2.0
SCRAPE_MAX_PAGES=500
RAG_TOP_K=8
RAG_SIMILARITY_THRESHOLD=0.05
```

---

**Last Updated:** 2026-04-30  
**Status:** All scrapers fully functional with automatic embedding generation
