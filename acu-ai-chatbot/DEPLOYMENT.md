# Cloud Deployment Guide

This guide covers deploying ACU AI Chatbot to a cloud VPS (DigitalOcean, Hetzner, AWS EC2, etc.).

The production stack replaces the local Ollama LLM with **Groq** (free API, no GPU required). Ollama still runs CPU-only for embedding generation.

## Prerequisites

- A VPS with at least **4 GB RAM** and **20 GB disk** (e.g. DigitalOcean $24/mo Droplet, Hetzner CX22)
- Docker and Docker Compose installed on the server
- A free Groq API key from [console.groq.com](https://console.groq.com)
- A domain name (optional, but recommended for HTTPS)

## Step 1 — Get a Free Groq API Key

1. Go to [console.groq.com](https://console.groq.com) and sign up
2. Navigate to **API Keys** → **Create API Key**
3. Copy the key — you'll need it in Step 3

## Step 2 — Provision a VPS

**DigitalOcean example:**
```bash
# Install Docker on Ubuntu 22.04
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

**Verify:**
```bash
docker --version
docker compose version
```

## Step 3 — Deploy the Application

```bash
# Clone or upload the project
git clone <your-repo-url> acu-ai-chatbot
cd acu-ai-chatbot

# Create .env from template
cp .env.example .env
```

Edit `.env` with your values:
```bash
# Required changes
POSTGRES_PASSWORD=<strong-random-password>
DJANGO_SECRET_KEY=<random-50-char-string>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=<your-server-ip-or-domain>

# Groq LLM (free, no GPU needed)
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile
GROQ_API_KEY=<your-groq-api-key>

# Embeddings via CPU Ollama
EMBEDDING_MODEL=bge-m3
```

Start the production stack:
```bash
docker compose -f docker-compose.prod.yml up -d
```

Monitor startup (bge-m3 download takes ~5 minutes on first run):
```bash
docker compose -f docker-compose.prod.yml logs -f ollama-init
docker compose -f docker-compose.prod.yml logs -f webapp
```

## Step 4 — Load Data

Once all services are healthy, scrape and index the university website:
```bash
docker compose -f docker-compose.prod.yml exec webapp \
    python manage.py scrape_acu --source=main

docker compose -f docker-compose.prod.yml exec webapp \
    python manage.py scrape_acu --source=bologna
```

Scraping takes ~30-60 minutes depending on network speed.

## Step 5 — Verify

```bash
# Health check
curl http://<your-server-ip>/api/health/

# Open the chat UI
open http://<your-server-ip>/
```

Admin panel: `http://<your-server-ip>/admin/` (credentials: `admin` / `admin123` — **change immediately**)

## Optional: HTTPS with Let's Encrypt

Install Certbot and update Nginx config:
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

Then add your domain to `.env`:
```
DJANGO_ALLOWED_HOSTS=yourdomain.com
```
And add it to `CSRF_TRUSTED_ORIGINS` in `webapp/config/settings.py`.

## Architecture on Cloud

```
Internet
   ↓
Nginx :80 (reverse proxy)
   ↓
Django/Gunicorn :8000
   ↓ (vectors + data)          ↓ (cache)          ↓ (LLM — external API)
PostgreSQL+pgvector           Redis              Groq API (HTTPS)
   ↑ (embeddings — local CPU)
Ollama :11434 (bge-m3 only)
```

## Recommended Cloud Providers

| Provider | Plan | RAM | Cost | Notes |
|----------|------|-----|------|-------|
| Hetzner | CX22 | 4 GB | ~€4/mo | Best value, EU datacenter |
| DigitalOcean | Basic | 4 GB | ~$24/mo | Easy setup, good docs |
| AWS EC2 | t3.medium | 4 GB | ~$30/mo | Free tier: t2.micro (not enough RAM) |
| Render.com | Standard | 2 GB | $25/mo | PaaS, no SSH needed |

## Troubleshooting

**webapp won't start:** Check `docker compose -f docker-compose.prod.yml logs webapp` — usually a missing env var or database connection issue.

**Ollama takes too long:** bge-m3 is ~1.2 GB. Let `ollama-init` finish before sending requests. Check with `docker compose logs ollama-init`.

**Groq rate limit:** Free tier allows 6000 tokens/minute. For high traffic, upgrade to a paid plan or add request throttling.
