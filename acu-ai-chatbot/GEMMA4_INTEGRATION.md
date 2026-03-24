# Gemma 4 E4B Integration Guide

## Current Setup Analysis

**Current LLM:** Configurable via `LLM_PROVIDER` (Ollama or TGI)
**Current Embedding Model:** nomic-embed-text (via Ollama)
**Settings:** `settings.py` (LLM_PROVIDER, LLM_MODEL, TGI_BASE_URL)

## Why Gemma 4 E4B?

- **Size:** Effective 4B (8B total parameters) fits a single GPU for local inference
- **Quality:** Strong multilingual performance, good Turkish output
- **Context:** Up to 128K context window (we cap tokens for performance)
- **Open weights:** Runs locally with no API fees

## Architecture Change

- **Generation:** Hugging Face TGI (Text Generation Inference) container
- **Embeddings:** Ollama (nomic-embed-text)
- **Routing:** Django selects provider via `LLM_PROVIDER`

## Step 1: Configure Environment

Update `.env` (or use the defaults from `.env.example`):

```bash
LLM_PROVIDER=tgi
LLM_MODEL=google/gemma-4-E4B-it
TGI_BASE_URL=http://tgi-gemma4:80
OLLAMA_BASE_URL=http://ollama:11434
EMBEDDING_MODEL=nomic-embed-text

# Optional: required if you must accept the Gemma license on Hugging Face
HF_TOKEN=hf_xxx
```

## Step 2: Start Services

```bash
docker-compose up -d
docker-compose logs -f tgi-gemma4
```

TGI will download the model the first time and can take several minutes.

## Step 3: Verify TGI Health

```bash
curl http://localhost:8080/health
```

Expected: HTTP 200 when the model is ready.

## Step 4: Test the Chat Endpoint

```bash
curl -X POST http://localhost:8000/api/chat/ \
    -H "Content-Type: application/json" \
    -d '{"question": "Acıbadem Üniversitesi nin misyonu nedir?"}'
```

## Rollback to Ollama (Optional)

Set the provider back to Ollama and restart:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:latest
```

```bash
docker-compose restart webapp
```

## Notes

- TGI is used for generation only; embeddings still come from Ollama.
- If you see 403 or download errors, set `HF_TOKEN` and ensure the model license is accepted.

## Troubleshooting

### TGI stuck on model download
- Ensure `HF_TOKEN` is set and the license is accepted on Hugging Face.
- Check logs: `docker-compose logs -f tgi-gemma4`

### GPU not detected
- Verify NVIDIA Container Toolkit is installed and Docker is using the NVIDIA runtime.
- Check container logs for CUDA errors.

## Status

Gemma 4 E4B via TGI is the default in docker-compose and `.env.example`.
