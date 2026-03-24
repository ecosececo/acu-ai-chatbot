# ACU Chatbot — Complete Quick-Start Checklist

Complete guide to get the chatbot running with the latest improvements.

## Phase 1: System Setup ✓

```bash
# 1. Ensure Docker Desktop is running
docker --version
docker-compose --version

# 2. Clone repo (if not already done)
cd d:\acu\acu-ai-chatbot

# 3. Start all services
docker-compose up -d

# 4. Wait 30-60 seconds for startup
# Check logs if needed:
docker-compose logs -f webapp
```

**Check:** All containers running
```bash
docker-compose ps
# Should show: webapp, db, redis, ollama, tgi-gemma4, nginx all "Up"
```

## Phase 2: Database Initialization ✓

```bash
# 1. Run migrations
docker-compose exec webapp python manage.py migrate --noinput

# 2. Collect static files
docker-compose exec webapp python manage.py collectstatic --noinput

# 3. Verify database
docker-compose exec webapp python manage.py shell
>>> from chat.models import WebPage, DocumentChunk
>>> WebPage.objects.count()  # Should show 0 initially
>>> exit()
```

## Phase 3: Scrape Content ✓

### Option A: Quick Test (20 minutes)
```bash
# Scrape limited content for testing
docker-compose exec webapp python manage.py scrape_acu --source=main --max-pages=50
```

### Option B: Full Production (45 minutes)
```bash
# Scrape everything
docker-compose exec webapp python manage.py scrape_acu --source=all

# This will:
# - Scrape ~500 main site pages
# - Scrape ~200-400 Bologna pages
# - Generate embeddings automatically
# - Index everything in PostgreSQL+pgvector
```

### Option C: Using Helper Script (Easiest)
```bash
# Make script executable (Windows: not needed)
chmod +x ops.sh

# Scrape everything
./ops.sh scrape all

# Or scrape individual sources
./ops.sh scrape main
./ops.sh scrape bologna
```

**Check Progress:**
```bash
# While scraping in another terminal
docker-compose exec webapp python manage.py shell
>>> from chat.services.rag_service import rag_service
>>> rag_service.get_stats()
```

## Phase 4: Verify Content Quality ✓

```bash
# Test with quality suite (14 real-world questions)
docker-compose exec webapp python test_chatbot_quality.py

# Expected: All 14 tests passing
# Expected time: ~3-5 minutes
```

## Phase 5: Access Chatbot ✓

Open browser:
```
http://localhost:80
or
http://localhost:8000
```

### Test Questions:
- "Ücret ne kadar?" (How much is tuition?)
- "Erasmus programı var mı?" (Is there an Erasmus program?)
- "Tıp fakültesi başvuru şartları nedir?" (What are medicine faculty requirements?)

## Phase 6 (Optional): Use Gemma 4 E4B (TGI)

```bash
# 1. Ensure env is set (or use .env.example defaults)
# LLM_PROVIDER=tgi
# LLM_MODEL=google/gemma-4-E4B-it
# TGI_BASE_URL=http://tgi-gemma4:80
# HF_TOKEN=hf_xxx (optional)

# 2. Start services
docker-compose up -d

# 3. Wait until TGI is ready
curl http://localhost:8080/health

# 4. Restart webapp if you changed env
docker-compose restart webapp
```

## Phase 7: Monitoring & Maintenance

### Check System Health
```bash
# View current stats
./ops.sh stats

# Check logs
./ops.sh logs webapp
./ops.sh logs db
./ops.sh logs ollama
```

### Re-Scrape if Needed
```bash
# Update main site only (keep Bologna intact)
./ops.sh scrape main --clear

# Update Bologna only (keep main site intact)
./ops.sh scrape bologna --clear

# Full refresh everything
./ops.sh scrape all --clear
```

### Performance Optimization
```bash
# If slow, check Docker resource allocation
# Settings > Resources > Increase CPUs and Memory

# If running out of space
docker system prune -a
```

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| "Connection refused" | Run `docker-compose up -d` |
| "No such image" | Run `docker-compose build` |
| "Database lock" | `docker-compose restart db` |
| "Slow responses" | Increase Docker RAM/CPU allocation |
| "Empty answers" | Re-scrape with `scrape all --clear` |
| "Playwright failed" | `docker-compose exec webapp pip install playwright` |

## Documentation Files

- **SCRAPING_GUIDE.md** — Detailed scraping commands and options
- **GEMMA4_INTEGRATION.md** — Model upgrade guide
- **CLAUDE.md** — Architecture and development guide
- **scrape_runner.py** — Python helper for scraping
- **ops.sh** — Bash helper for all operations

## API Endpoints

```bash
# Chat endpoint (returns JSON)
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"question": "Merhaba"}'

# Streaming endpoint (Server-Sent Events)
curl -X POST "http://localhost:8000/api/chat/?stream=true" \
  -H "Content-Type: application/json" \
  -d '{"question": "Merhaba"}'

# Stats
curl http://localhost:8000/api/stats/

# Health check
curl http://localhost:8000/api/health/
```

## Performance Targets

- Page load: <1s
- Chat response: 2-4s (Gemma 4 E4B, GPU)
- RAG search: <500ms
- Embedding generation: <100ms per chunk

## Next Steps

1. ✓ Complete Phase 1-5 above
2. ✓ Test with real questions
3. ✓ (Optional) Tune LLM provider/model
4. ✓ Share with users
5. ✓ Monitor and refine based on feedback

## Emergency Commands

```bash
# Stop everything
docker-compose down

# Start fresh
docker-compose down -v
docker-compose up -d

# View all logs
docker-compose logs -f

# Database shell
docker-compose exec db psql -U acu_user -d acu_chatbot

# Django shell
docker-compose exec webapp python manage.py shell

# Container shell
docker-compose exec webapp bash
```

## Success Indicators

- [x] All containers running
- [x] Database initialized
- [x] 500+ pages scraped
- [x] 5000+ chunks created
- [x] Quality tests passing (14/14)
- [x] Web UI loads quickly
- [x] Responses are accurate and in Turkish

## Support

For detailed information:
- Architecture: See `CLAUDE.md`
- Scraping: See `SCRAPING_GUIDE.md`
- Model upgrade: See `GEMMA4_INTEGRATION.md`

---

**Estimated Total Time:** 60-90 minutes  
**Difficulty:** Easy (just follow the steps)  
**Last Updated:** 2026-04-30
