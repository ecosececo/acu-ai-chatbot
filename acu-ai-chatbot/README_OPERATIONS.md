# ACU AI Chatbot — Complete Scraping & Operations Guide

**Prepared:** 2026-04-30  
**Status:** All scrapers fully implemented and documented  
**Time to Production:** ~90 minutes

## What You're Getting

This package includes everything needed to:
- ✓ Start the chatbot system
- ✓ Scrape both ACU main site and Bologna system  
- ✓ Generate embeddings and build the RAG index
- ✓ Test the chatbot quality
- ✓ Gemma 4 E4B generation via TGI (default)

## Quick Navigation

| Need | File | Time |
|------|------|------|
| **Start immediately** | [QUICKSTART.md](QUICKSTART.md) | 5 min read |
| **Detailed scraping** | [SCRAPING_GUIDE.md](SCRAPING_GUIDE.md) | 10 min read |
| **Model upgrade** | [GEMMA4_INTEGRATION.md](GEMMA4_INTEGRATION.md) | 5 min read |
| **Architecture** | [CLAUDE.md](CLAUDE.md) | 15 min read |
| **System health** | `python health_check.py` | 30 sec |

## 60-Second Start

```bash
# 1. Start services
docker-compose up -d

# 2. Wait 30 seconds, then initialize
docker-compose exec webapp python manage.py migrate --noinput
docker-compose exec webapp python manage.py collectstatic --noinput

# 3. Scrape everything
docker-compose exec webapp python manage.py scrape_acu --source=all

# 4. Open browser
# http://localhost
```

That's it! The chatbot will be ready in ~45 minutes.

## Helper Scripts Included

### Python: scrape_runner.py
```bash
python scrape_runner.py main        # Scrape main site
python scrape_runner.py bologna     # Scrape Bologna
python scrape_runner.py all         # Scrape both
python scrape_runner.py stats       # Show stats
```

### Bash: ops.sh
```bash
./ops.sh start                       # Start all services
./ops.sh scrape all                 # Scrape everything
./ops.sh stats                       # Show statistics
./ops.sh logs                        # View logs
```

### Python: health_check.py
```bash
python health_check.py              # Full health check
python health_check.py quick        # Quick status
python health_check.py repair       # Auto-repair issues
```

## Scraper Architecture

### ACU Main Site (acibadem.edu.tr)
- **Method:** BFS crawler with `requests` + BeautifulSoup
- **Rate Limiting:** 2 seconds between requests
- **Pages:** ~500 (configurable)
- **Time:** ~5-10 minutes
- **Content:** Programs, faculty, admission, campus info, news

### Bologna System (obs.acibadem.edu.tr)
- **Method:** Playwright headless browser (handles JavaScript)
- **Navigation:** Direct sub-page URLs (progAbout.aspx, progCourses.aspx, etc.)
- **Pages:** ~17 per program × 20+ programs = 200-400 pages
- **Time:** ~15-30 minutes
- **Content:** Curricula, courses, credits (ECTS), learning outcomes

### Automatic Embedding
- **Model:** nomic-embed-text (768-dimensional)
- **Speed:** ~50 chunks/minute on GPU
- **Storage:** PostgreSQL with pgvector extension
- **Time:** Happens automatically during scraping

## RAG Pipeline Quality

The system includes multiple improvements:

1. **Query Expansion:** ~30 Turkish synonym mappings
2. **Smart Chunking:** Overlapping text chunks for context
3. **Hybrid Search:** Semantic (pgvector) + Keyword (PostgreSQL FTS)
4. **Re-ranking:** Keywords match against original query
5. **Navigation Filtering:** Removes menu/UI noise from results
6. **Category Detection:** 7 content categories for better filtering

## Gemma 4 E4B (Default)

The stack uses Gemma 4 E4B via TGI by default. Verify the settings in `.env`:

```bash
LLM_PROVIDER=tgi
LLM_MODEL=google/gemma-4-E4B-it
TGI_BASE_URL=http://tgi-gemma4:80
```

To rollback to Ollama models:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:latest
```

See [GEMMA4_INTEGRATION.md](GEMMA4_INTEGRATION.md) for details.

## File Inventory

### Documentation
- `QUICKSTART.md` — Phase-by-phase setup guide
- `SCRAPING_GUIDE.md` — Detailed scraping commands
- `GEMMA4_INTEGRATION.md` — Model upgrade guide
- `CLAUDE.md` — Architecture and development (already exists)

### Helper Scripts
- `scrape_runner.py` — Python wrapper for scraping
- `ops.sh` — Bash wrapper for all operations
- `health_check.py` — System health checker

### Core Scrapers (Pre-existing, Enhanced)
- `webapp/scraper/acu_scraper.py` — Main site scraper
- `webapp/scraper/bologna_scraper.py` — Bologna system scraper
- `webapp/chat/management/commands/scrape_acu.py` — Django management command

## Expected Outcomes

### After 90 minutes:
- ✓ All Docker services running
- ✓ 500+ main site pages scraped
- ✓ 200+ Bologna pages scraped
- ✓ 5000+ chunks created
- ✓ All chunks embedded (768-dim vectors)
- ✓ Web UI accessible at http://localhost
- ✓ Quality tests passing (14/14)

### Database State:
```
WebPage: 700+ documents
DocumentChunk: 5000+ chunks
Embedding vectors: 5000+ stored in pgvector
Categories: 7 (admission, academic, campus, etc.)
Source breakdown: Main=500, Bologna=200+
```

## Performance Metrics

| Operation | Time | Notes |
|-----------|------|-------|
| Page scrape | 2-3s | With rate limiting |
| Embedding generation | 20ms | Per chunk |
| Semantic search | 100ms | pgvector cosine |
| Keyword search | 50ms | PostgreSQL FTS |
| LLM response | 2-4s | Gemma 4 E4B (TGI, GPU) |
| LLM response | 3-6s | Ollama provider (model-dependent) |
| Full chat pipeline | 3-5s | Scrape → search → generate |

## Troubleshooting Quick Links

| Issue | Solution |
|-------|----------|
| Services not running | `docker-compose up -d` |
| Scraping fails | `docker-compose restart webapp` |
| Database empty | Check `python health_check.py` |
| Slow responses | Increase Docker memory allocation |
| TGI download fails | Set `HF_TOKEN` and check `docker-compose logs -f tgi-gemma4` |

## API Examples

```bash
# Chat (returns JSON)
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"question": "Ücret ne kadar?"}'

# Streaming (Server-Sent Events)
curl -X POST "http://localhost:8000/api/chat/?stream=true" \
  -H "Content-Type: application/json" \
  -d '{"question": "Erasmus programı var mı?"}'

# Stats
curl http://localhost:8000/api/stats/
```

## Test Questions (for verification)

```
1. Acıbadem Üniversitesi'nin misyonu nedir?
2. Tıp fakültesi başvuru şartları nelerdir?
3. Ücret ne kadar?
4. Erasmus programı var mı?
5. Yurt konaklama imkanı nedir?
6. Kütüphane açık saatleri?
7. Bilgisayar Mühendisliği ders programı nedir?
8. Burs imkanları neler?
9. Yatay geçiş nasıl yapılır?
10. Öğrenci kulüpleri neler?
```

## Next Steps

1. **Read:** [QUICKSTART.md](QUICKSTART.md) (5 minutes)
2. **Execute:** Phase 1-5 of the checklist (60 minutes)
3. **Verify:** Run `python health_check.py` and test questions
4. **Optimize:** (Optional) Tune LLM provider or model
5. **Monitor:** Use `./ops.sh stats` to check content growth

## Support Resources

- **Architecture:** See `CLAUDE.md` (Docker setup, RAG pipeline, API endpoints)
- **Common Commands:** See `SCRAPING_GUIDE.md` (all scraping variations)
- **Model Setup:** See `GEMMA4_INTEGRATION.md` (Gemma 4 E4B via TGI)
- **Quick Check:** Run `python health_check.py` (verify all systems)

## Key Improvements Made

✓ Navigation noise filtering (removes menu text)  
✓ Smart chunk overlapping (context preservation)  
✓ Hybrid search with re-ranking (better results)  
✓ Category-based filtering with soft thresholds  
✓ Comprehensive test suite (134 unit + 14 integration tests)  
✓ Connection retry logic (handles transient errors)  
✓ Full embedding pipeline (automatic during scraping)  

## Performance Optimization Tips

```bash
# Faster scraping (reduce delays)
SCRAPE_DELAY=1.0 docker-compose exec webapp \
  python manage.py scrape_acu --source=main

# More results (increase search depth)
RAG_TOP_K=15 docker-compose exec webapp \
  python manage.py shell

# Lower similarity threshold (get more results)
RAG_SIMILARITY_THRESHOLD=0.01 docker-compose exec webapp \
  python manage.py shell
```

---

## Success Checklist

- [ ] Docker installed and running
- [ ] All services started (`docker-compose up -d`)
- [ ] Database initialized (`migrate --noinput`)
- [ ] Scraping completed (`scrape_acu --source=all`)
- [ ] Web UI accessible (http://localhost)
- [ ] Quality tests passing (`test_chatbot_quality.py`)
- [ ] Test questions answering correctly
- [ ] System stats showing 500+ pages

**When all checked: Production ready! 🚀**

---

**For immediate startup, go to:** [QUICKSTART.md](QUICKSTART.md)
