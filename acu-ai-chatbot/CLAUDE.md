# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ACU AI Chatbot — a RAG-powered Turkish-language chatbot for Acıbadem University (ACU). Uses Qwen 3.5 via Ollama for generation, bge-m3 via Ollama for embeddings, pgvector for semantic search, and a hybrid retrieval pipeline designed specifically for Turkish academic content.

## Common Commands

### Docker (primary workflow)
```bash
docker-compose up -d                              # Start all services
docker-compose exec webapp python manage.py migrate --noinput
docker-compose exec webapp python manage.py collectstatic --noinput
docker-compose exec webapp python manage.py scrape_acu --source main
docker-compose exec webapp python manage.py scrape_acu --source bologna
```

### Running Tests
```bash
docker-compose exec webapp python manage.py test --verbosity=2
```

### Linting
```bash
cd webapp && pip install ruff && ruff check . --ignore E501
```

### Local Development (requires PostgreSQL+pgvector, Redis, and Ollama running separately)
```bash
cd webapp
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8000
```

## Architecture

Six Docker services:

```
Nginx :80 → Django/Gunicorn :8000 → PostgreSQL 16 + pgvector :5432
                                  → Ollama :11434 (bge-m3 embeddings + Qwen 3.5 LLM)
                                  → Redis :6379 (cache)
```

Ollama handles both embeddings and generation. An `ollama-init` one-shot service pulls `bge-m3` and `qwen3.5` on first start. The optional TGI service (Gemma 4) can be re-enabled by setting `LLM_PROVIDER=tgi`.

## RAG Pipeline

The core intelligence lives in [webapp/chat/services/rag_service.py](webapp/chat/services/rag_service.py):

1. **Query expansion** — ~30 Turkish synonym mappings (e.g., `ücret → öğrenim ücreti`)
2. **Category detection** — 7 categories (admission, academic, campus, etc.) matched by keyword patterns
3. **Hybrid search** — semantic (pgvector cosine) + keyword (PostgreSQL `LIKE`) run in parallel
4. **Reciprocal Rank Fusion** — merges results with semantic weighted 1.5×
5. **Re-ranking** — keyword density scoring against original query

Context budget: max 9000 chars, 3 sources max. Embeddings: 1024-dimensional `bge-m3` stored in `DocumentChunk.embedding` (pgvector `VectorField`).

## LLM Service

[webapp/chat/services/llm_service.py](webapp/chat/services/llm_service.py) is a singleton wrapping the configured LLM provider (TGI or Ollama):

- Temperature 0.3, top_p 0.85, max tokens 1024
- System prompt in Turkish emphasizing RAG grounding (no hallucination)
- Streaming via Server-Sent Events (`/api/chat/?stream=true`)
- LLM availability is cached in Redis with 15-30s TTL

## Web Search

[webapp/chat/services/web_search_service.py](webapp/chat/services/web_search_service.py) uses DuckDuckGo and is **disabled by default** (`WEB_SEARCH_ENABLED=False`). It only triggers when the best RAG similarity score falls below a threshold.

## Data Models

- **`WebPage`** — scraped pages with url (unique), content, source (`main`/`bologna`), category
- **`DocumentChunk`** — chunked text with 1024d vector embedding and JSON metadata
- **`Conversation`** — UUID PK, session-based (anonymous users), last 6 messages kept for context window
- **`Message`** — role, content, `context_used`, `sources` (JSON), `response_time_ms`

## Scraper

[webapp/scraper/acu_scraper.py](webapp/scraper/acu_scraper.py) is a BFS crawler with:
- 95 seed URLs in the management command
- 2s rate limiting between requests (configurable via `SCRAPE_DELAY`)
- Skip patterns for PDFs, login pages, English pages, JS/mailto links
- Max 500 pages (configurable via `SCRAPE_MAX_PAGES`)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat/` | Chat (add `?stream=true` for SSE) |
| GET | `/api/conversations/` | List conversations |
| GET/DELETE | `/api/conversations/{id}/` | Conversation detail/delete |
| GET | `/api/stats/` | System stats |
| GET | `/api/health/` | Health check |
| GET | `/` | Web UI |

## Key Configuration (settings.py)

- `LLM_PROVIDER` — `ollama` (default) or `tgi`
- `LLM_MODEL` — model name (default: `qwen3.5`)
- `OLLAMA_BASE_URL` — Ollama endpoint (default: `http://ollama:11434`)
- `EMBEDDING_MODEL` — embedding model (default: `bge-m3`)
- `EMBEDDING_DIMENSIONS` — 1024
- `RAG_TOP_K` — number of retrieved chunks (default: 8)
- `RAG_SIMILARITY_THRESHOLD` — minimum similarity score (default: 0.05)
- `WEB_SEARCH_ENABLED` — toggle DuckDuckGo fallback (default: False)

Copy `.env.example` to `.env` and fill in `POSTGRES_*` and `DJANGO_SECRET_KEY`.

## Cloud Deployment

Production deployment uses `docker-compose.prod.yml` which swaps the Ollama LLM for **Groq** (free API, no GPU) while keeping CPU-only Ollama for embeddings. See `DEPLOYMENT.md` for the full step-by-step guide.

**Key differences from local stack:**
- `LLM_PROVIDER=groq` + `GROQ_API_KEY` — no GPU needed, free tier available
- `OLLAMA_NUM_GPU=0` — Ollama runs CPU-only for bge-m3 embeddings only
- `DJANGO_DEBUG=False`, strong `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` required

Recommended server: 4 GB RAM minimum (Hetzner CX22 ~€4/mo or DigitalOcean $24/mo).

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs three jobs on push/PR to `main` and `develop`:

1. **lint** — `ruff check` on `webapp/`, ignores E501 (line length)
2. **test** — Django test suite against real PostgreSQL 16+pgvector and Redis service containers; LLM calls are mocked so no Ollama needed
3. **docker-build** — builds `webapp` and `nginx` images with layer caching, then validates `docker-compose.yml` via `docker compose config`

The `.github/` directory lives at the repo root (`aiaiai/`), not inside `acu-ai-chatbot/`. Paths in the workflow are prefixed with `acu-ai-chatbot/`.

## Nginx

`/api/chat/` has SSE-specific config: proxy buffering disabled, 300s timeout. Static files served directly via WhiteNoise. Security headers set (`X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`).

## Admin

Superuser is auto-created on container startup (`admin` / `admin123`). The admin interface has rich inlines: messages within conversations, chunks within pages. `DocumentChunk` and `Message` are read-only in admin (immutable RAG data).
