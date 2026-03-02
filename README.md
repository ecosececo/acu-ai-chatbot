# 🎓 ACU AI Chatbot

**Acıbadem Üniversitesi AI Chatbot** — A Django web application powered by a local open-source LLM, fully containerized with Docker & Docker Compose.

> CSE 322 – Cloud Computing | Spring 2026

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Quick Start](#quick-start)
- [Features](#features)
- [Project Structure](#project-structure)
- [API Documentation](#api-documentation)
- [Data Collection](#data-collection)
- [AI Integration](#ai-integration)
- [Configuration](#configuration)
- [Development](#development)
- [Testing](#testing)
- [Deployment](#deployment)
- [Team Members](#team-members)

---

## 🔭 Overview

This project implements an AI-powered chatbot that answers questions about Acıbadem University using data collected from the university's official websites. The chatbot uses:

- **RAG (Retrieval-Augmented Generation)** with pgvector for semantic search
- **Mistral 7B** (via Ollama) as the local LLM
- **Django 5.x** for the web application
- **PostgreSQL 16** with pgvector extension for vector storage
- **Server-Sent Events (SSE)** for streaming responses

## 🏗️ Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│    Nginx     │────▶│   Django    │────▶│   PostgreSQL    │
│  (Reverse    │     │   (Web App  │     │   + pgvector    │
│   Proxy)     │     │    + API)   │     │  (Vector Store) │
│   :80        │     │   :8000     │     │   :5432         │
└─────────────┘     └──────┬──────┘     └─────────────────┘
                           │
                    ┌──────┴──────┐
                    │             │
              ┌─────▼────┐  ┌────▼────┐
              │  Ollama   │  │  Redis  │
              │  (LLM +   │  │ (Cache) │
              │ Embeddings│  │  :6379  │
              │  :11434   │  └─────────┘
              └──────────┘
```

### Data Flow

1. User types a question in the chat interface
2. Django receives the request via REST API
3. **RAG Pipeline**: Query is embedded → pgvector semantic search finds relevant chunks
4. Retrieved context + question are sent to Ollama (Mistral)
5. LLM generates a response grounded in university data
6. Response is streamed back to the user via SSE

## 🛠️ Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Web Framework | Django 5.x | REST API + Chat Interface |
| Database | PostgreSQL 16 + pgvector | Data storage + Vector search |
| LLM | Mistral 7B (via Ollama) | Answer generation |
| Embeddings | nomic-embed-text (via Ollama) | Semantic embeddings (768 dims) |
| Cache | Redis 7 | Response caching |
| Reverse Proxy | Nginx | Static files + SSE streaming |
| Containerization | Docker + Docker Compose | Full orchestration |
| CI/CD | GitHub Actions | Automated testing + builds |

## 🚀 Quick Start

### Prerequisites

- Docker Engine 24+ and Docker Compose v2
- At least **8 GB RAM** (for LLM model)
- 15 GB+ free disk space

### 1. Clone & Configure

```bash
git clone https://github.com/your-team/acibadem-chatbot.git
cd acibadem-chatbot

# Copy environment file
cp .env.example .env
# Edit .env if needed (defaults work for local development)
```

### 2. Start Everything

```bash
docker-compose up -d
```

This single command will:
- Start PostgreSQL with pgvector
- Start Redis cache
- Start Ollama and pull the Mistral model (~4GB download, first time only)
- Start the Django application (with migrations & static files)
- Start Nginx reverse proxy

### 3. Load Data & Generate Embeddings

```bash
# Load curated seed data about ACU
docker-compose exec webapp python manage.py load_seed_data

# Generate vector embeddings for RAG
docker-compose exec webapp python manage.py generate_embeddings

# (Optional) Scrape live data from ACU websites
docker-compose exec webapp python manage.py scrape_acu --source main
docker-compose exec webapp python manage.py scrape_acu --source bologna
docker-compose exec webapp python manage.py generate_embeddings
```

### 4. Access the Application

| Service | URL |
|---------|-----|
| **Chat Interface** | http://localhost |
| **Admin Panel** | http://localhost/admin/ |
| **API Docs** | http://localhost/api/ |

**Admin credentials**: `admin` / `admin123`

## ✨ Features

### Core Requirements
- ✅ Chat interface with real-time AI responses
- ✅ Chat history stored in PostgreSQL
- ✅ Django Admin panel for data & chat management
- ✅ REST API (`POST /api/chat/`)
- ✅ Error handling (graceful LLM unavailability messages)
- ✅ Web scraping for ACU websites
- ✅ Local LLM (Mistral via Ollama)
- ✅ Docker Compose orchestration

### Bonus Features
- ✅ **RAG with pgvector** — Semantic search with vector embeddings
- ✅ **Nginx reverse proxy** — Static file serving + SSE support
- ✅ **Redis caching** — Response and health check caching
- ✅ **Streaming responses (SSE)** — Real-time token-by-token output
- ✅ **CI/CD Pipeline** — GitHub Actions for testing + Docker builds
- ✅ **Dark/Light theme** — User-selectable theme
- ✅ **Responsive design** — Mobile-friendly interface

## 📁 Project Structure

```
acibadem-chatbot/
├── docker-compose.yml          # Full orchestration (6 services)
├── .env.example                # Environment variables template
├── .gitignore
├── README.md
│
├── webapp/                     # Django Application
│   ├── Dockerfile              # Multi-stage build
│   ├── entrypoint.sh           # Auto-migration + static collection
│   ├── requirements.txt
│   ├── manage.py
│   │
│   ├── config/                 # Django Project Settings
│   │   ├── settings.py         # Configuration (DB, cache, LLM, RAG)
│   │   ├── urls.py             # URL routing
│   │   ├── wsgi.py
│   │   └── asgi.py
│   │
│   ├── chat/                   # Main Chat Application
│   │   ├── models.py           # WebPage, DocumentChunk, Conversation, Message
│   │   ├── views.py            # API views + chat interface
│   │   ├── serializers.py      # DRF serializers
│   │   ├── admin.py            # Admin configuration
│   │   ├── urls.py             # Web URLs
│   │   ├── api_urls.py         # API URLs
│   │   ├── tests.py            # Unit tests
│   │   │
│   │   ├── services/           # Business Logic
│   │   │   ├── llm_service.py  # Ollama communication + prompt engineering
│   │   │   └── rag_service.py  # RAG pipeline (chunk → embed → search)
│   │   │
│   │   └── management/commands/
│   │       ├── scrape_acu.py       # Web scraper command
│   │       ├── generate_embeddings.py  # Embedding generator
│   │       └── load_seed_data.py       # Curated seed data loader
│   │
│   ├── scraper/                # Web Scraping Module
│   │   ├── acu_scraper.py      # Main site scraper
│   │   └── bologna_scraper.py  # Bologna system scraper
│   │
│   ├── static/                 # Frontend Assets
│   │   ├── css/style.css       # Modern dark/light theme
│   │   └── js/chat.js          # Chat logic + SSE streaming
│   │
│   └── templates/chat/
│       └── index.html          # Chat interface template
│
├── nginx/                      # Reverse Proxy
│   ├── Dockerfile
│   └── nginx.conf              # Proxy + SSE + compression config
│
├── .github/workflows/
│   └── ci.yml                  # CI/CD pipeline
│
└── docs/
    └── architecture.md         # Architecture documentation
```

## 📡 API Documentation

### POST /api/chat/
Main chat endpoint. Send a question and receive an AI answer.

**Request:**
```json
{
    "question": "Bilgisayar Mühendisliği bölümünde hangi dersler var?",
    "conversation_id": "uuid (optional)",
    "stream": false
}
```

**Response:**
```json
{
    "answer": "Bilgisayar Mühendisliği bölümünde şu dersler bulunmaktadır: ...",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
    "sources": [
        {
            "url": "https://obs.acibadem.edu.tr/...",
            "title": "Bilgisayar Mühendisliği - Ders Programı",
            "score": 0.89
        }
    ],
    "model": "mistral",
    "response_time_ms": 3450
}
```

### GET /api/conversations/
List all conversations for the current session.

### GET /api/conversations/{id}/
Get conversation with all messages.

### DELETE /api/conversations/{id}/delete/
Delete a conversation.

### GET /api/stats/
System statistics (pages, chunks, conversations, LLM status).

### GET /api/health/
Health check endpoint.

## 🕷️ Data Collection

### Strategy: Hybrid (Seed + Scraping)

1. **Seed Data** — High-quality, manually curated content (always available)
   - University overview, faculties, departments
   - Course catalogs, admission info, campus life
   - Loaded via `python manage.py load_seed_data`

2. **Web Scraping** — Automated collection from live websites
   - `acibadem.edu.tr` — Main site (BeautifulSoup + requests)
   - `obs.acibadem.edu.tr` — Bologna system (academic programs)
   - Respectful scraping with 2-second delays
   - Run via `python manage.py scrape_acu`

### Data Sources
| Source | URL | Content |
|--------|-----|---------|
| Main Site | acibadem.edu.tr | General info, faculties, admission |
| Bologna | obs.acibadem.edu.tr | Courses, curricula, ECTS, outcomes |

## 🤖 AI Integration

### Model: Mistral 7B
- **Parameters**: 7 billion
- **Size**: ~4 GB
- **Serving**: Ollama (HTTP API)
- **Why**: Best quality-to-size ratio, strong multilingual (Turkish) support

### RAG Pipeline
1. **Chunking**: Documents split into ~512-char overlapping chunks
2. **Embedding**: nomic-embed-text model (768 dimensions) via Ollama
3. **Storage**: pgvector in PostgreSQL (cosine similarity index)
4. **Retrieval**: Top-K semantic search on user query
5. **Augmentation**: Retrieved chunks injected as context in LLM prompt

### Prompt Engineering
The system uses carefully crafted prompts:
- **System prompt**: Defines the assistant's role, rules, and response format
- **User prompt template**: Structures context + question for the LLM
- **Guard rails**: Prevents hallucination (answer only from provided context)
- **Language handling**: Auto-detects Turkish/English questions
- **Source attribution**: Instructs the model to cite sources

## ⚙️ Configuration

All configuration via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL` | `mistral` | Ollama model name |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `POSTGRES_DB` | `acu_chatbot` | Database name |
| `DJANGO_DEBUG` | `True` | Debug mode |
| `SCRAPE_DELAY` | `2.0` | Seconds between scrape requests |
| `SCRAPE_MAX_PAGES` | `500` | Max pages to scrape |

### Using a Different Model

Change the model in `.env`:
```bash
# Smaller, faster model
LLM_MODEL=gemma2:2b

# Larger, more capable
LLM_MODEL=llama3.1:8b

# Reasoning-focused
LLM_MODEL=deepseek-r1:7b
```

## 🧪 Testing

```bash
# Run tests inside Docker
docker-compose exec webapp python manage.py test --verbosity=2

# Run tests locally
cd webapp
pip install -r requirements.txt
DATABASE_URL=postgresql://... python manage.py test
```

## 🚢 Deployment

### Cloud Deployment (GCP/AWS/Azure)

1. Push Docker images to a container registry
2. Deploy with Docker Compose or Kubernetes
3. Configure persistent volumes for PostgreSQL and Ollama models
4. Set `DJANGO_DEBUG=False` and proper `DJANGO_SECRET_KEY`

### Kubernetes (Minikube)

Kubernetes manifests can be generated from the docker-compose.yml using `kompose`:
```bash
kompose convert -f docker-compose.yml -o k8s/
```

---

## 👥 Team Members

| Name | Role | Contributions |
|------|------|--------------|
| Eceyül Şen (ecosececo) | Backend & AI | Django app, LLM integration, RAG pipeline |
| Arda Hazar (ardahzr) | Frontend & DevOps | Chat UI, Docker, CI/CD |
| Ömer Valiyev (OmerV7) | Data & Testing | Web scraping, seed data, testing |

---

## 📄 License

This project is developed for educational purposes as part of CSE 322 — Cloud Computing course at Acıbadem University.

