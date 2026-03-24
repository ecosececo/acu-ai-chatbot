# Architecture Documentation

## System Architecture

The ACU AI Chatbot system consists of 6 containerized services orchestrated via Docker Compose:

```
                         ┌──── Internet ────┐
                         │                  │
                         ▼                  │
                 ┌───────────────┐          │
                 │    Nginx      │          │
                 │  Port 80      │          │
                 │  - Reverse    │          │
                 │    Proxy      │          │
                 │  - Static     │          │
                 │    Files      │          │
                 │  - Gzip       │          │
                 │  - SSE        │          │
                 └───────┬───────┘          │
                         │                  │
                         ▼                  │
                 ┌───────────────┐          │
                 │  Django App   │          │
                 │  Port 8000    │          │
                 │               │          │
                 │  - Chat UI    │          │
                 │  - REST API   │          │
                 │  - Admin      │          │
                 │  - RAG Engine │          │
                 │  - Scraper    │          │
                 └───┬───┬───┬───┘          │
                     │   │   │              │
          ┌──────────┘   │   └──────────┐   │
          ▼              ▼              ▼              ▼
  ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
  │ PostgreSQL   │ │  Redis   │ │   TGI    │ │  Ollama  │
  │ + pgvector   │ │  Cache   │ │  LLM     │ │ Embedding│
  │ Port 5432    │ │ Port 6379│ │ Port 8080│ │Port 11434│
  │              │ │          │ │          │ │          │
  │ - Web Pages  │ │ - Health │ │ - Gemma  │ │ - nomic  │
  │ - Chunks     │ │   Cache  │ │   4 E4B  │ │   embed  │
  │ - Vectors    │ │ - Query  │ │          │ │          │
  │ - Chat Hist. │ │   Cache  │ │          │ │          │
  │ - Sessions   │ │          │ │          │ │          │
  └──────────────┘ └──────────┘ └──────────┘ └──────────┘
```

## RAG (Retrieval-Augmented Generation) Pipeline

```
User Question
      │
      ▼
┌─────────────┐     ┌────────────────┐     ┌─────────────────┐
│  Embed      │────▶│  pgvector      │────▶│  Top-K Relevant │
│  Query      │     │  Cosine Search │     │  Chunks         │
│  (768 dims) │     │                │     │                 │
└─────────────┘     └────────────────┘     └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌────────────────┐
                                            │  Build Context │
                                            │  (Title, URL,  │
                                            │   Content)     │
                                            └────────┬───────┘
                                                     │
                                                     ▼
                                            ┌────────────────┐
                                            │  System Prompt │
                                            │  + Context     │──▶  TGI API
                                            │  + Question    │     (Gemma 4 E4B)
                                            └────────────────┘          │
                                                                        │
                                                                        ▼
                                                               ┌────────────────┐
                                                               │  AI Response   │
                                                               │  (Streamed     │
                                                               │   via SSE)     │
                                                               └────────────────┘
```

## Docker Services

| Service | Image | Purpose | Ports |
|---------|-------|---------|-------|
| nginx | Custom (nginx:1.25-alpine) | Reverse proxy, static files, SSE | 80 |
| webapp | Custom (python:3.12-slim) | Django app (Gunicorn) | 8000 |
| db | pgvector/pgvector:pg16 | PostgreSQL + vector extension | 5432 |
| redis | redis:7-alpine | Cache layer | 6379 |
| tgi-gemma4 | ghcr.io/huggingface/text-generation-inference | LLM generation (Gemma 4 E4B) | 8080 |
| ollama | ollama/ollama:latest | Embedding model serving | 11434 |

## Data Flow

### Chat Request Flow
1. Browser → Nginx (port 80)
2. Nginx → Django/Gunicorn (port 8000)
3. Django → RAG Service → pgvector search
4. Django → TGI API (port 8080) with context
5. TGI → Django (streamed response)
6. Django → Nginx → Browser (SSE stream)

### Data Ingestion Flow
1. Scraper fetches pages from ACU websites
2. Pages stored in PostgreSQL (WebPage model)
3. Text chunked into ~512-char segments
4. Each chunk embedded via Ollama (nomic-embed-text)
5. Embeddings stored in pgvector (DocumentChunk model)
6. Available for semantic search during chat
