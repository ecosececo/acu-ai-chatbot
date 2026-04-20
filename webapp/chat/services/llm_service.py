"""
LLM Service — Communicates with Ollama to generate AI responses.
Handles prompt engineering, streaming, and error handling.
"""

import json
import logging
import re
import time
from typing import Generator

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

NO_CONTEXT_FALLBACK_MESSAGE = (
    "Bu konuda yeterli bilgi bulunamadı. Lütfen sorunuzu farklı şekilde sormayı deneyin."
)

SYSTEM_PROMPT = """Sen Acıbadem Üniversitesi için bir bilgi asistanısın.
Sana verilen BAĞLAM METNİNDEN soruyu yanıtla.

KURAL 1: Yanıtında YALNIZCA bağlam metnindeki bilgileri kullan. Bağlamda olmayan bilgi ekleme.
KURAL 2: Bağlamda cevap yoksa sadece şunu yaz: "Bu konuda bilgi bulunamadı."
KURAL 3: SADECE TÜRKÇE yaz. İngilizce, Japonca, Çince veya başka dil kesinlikle kullanma. Kısa ve net cümleler kur. Doğrudan yanıta başla."""

USER_PROMPT_TEMPLATE = """BAĞLAM (Acıbadem Üniversitesi resmi sitesinden alınan bilgiler):
{context}

SORU: {question}

Yukarıdaki BAĞLAM metnini kullanarak soruyu yanıtla. Bağlam dışı bilgi ekleme.
ÖNEMLİ: Bağlamda "Hayır" veya "değildir" varsa bunu koru. Kendi bilgini kullanma.
Yanıt:"""


_NOISE_PREFIXES = re.compile(
    r"^(kısa cevap|short answer|cevap|yanıt|özet)\s*[:：]\s*",
    re.IGNORECASE,
)


def _strip_rag_metadata(context: str) -> str:
    """Remove RAG metadata and markdown heading markers from context before sending to LLM."""
    lines = []
    for line in context.splitlines():
        stripped = line.strip()
        # Drop RAG structural metadata lines
        if stripped.startswith("### Kaynak"):
            continue
        if stripped.startswith("URL:"):
            continue
        if stripped.startswith("Benzerlik Skoru:"):
            continue
        if stripped == "---":
            lines.append("")
            continue
        # Convert markdown headings to plain text (keep the label, drop the # marks)
        cleaned_line = re.sub(r"^#{1,4}\s+", "", line.strip())
        lines.append(cleaned_line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


_NON_TURKISH_BLOCK = re.compile(
    r"[\u2E80-\u9FFF\uF900-\uFAFF\uFE30-\uFE4F\uFF00-\uFFEF\u3000-\u303F]+"
)


def _clean_answer(text: str) -> str:
    """Remove model-injected noise prefixes and non-Turkish script garbage."""
    text = text.strip()
    text = _NOISE_PREFIXES.sub("", text).strip()
    text = re.sub(r"^\n+", "", text)
    # Truncate at first CJK/full-width character block (model switching to Chinese/Japanese)
    match = _NON_TURKISH_BLOCK.search(text)
    if match:
        text = text[: match.start()].rstrip()
    return text


class LLMService:
    """Handles all communication with the Ollama LLM service."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.LLM_MODEL
        self.timeout = httpx.Timeout(timeout=300.0, connect=10.0)

    def is_available(self) -> bool:
        """Check if Ollama service is running and the model is available."""
        cache_key = "ollama_available"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
                response = client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_names = [m["name"] for m in models]
                    available = self.model in model_names or any(
                        self.model.split(":")[0] == n.split(":")[0] for n in model_names
                    )
                    cache.set(cache_key, available, timeout=30)
                    return available
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            cache.set(cache_key, False, timeout=10)
            return False

        cache.set(cache_key, False, timeout=10)
        return False

    def _build_user_prompt(self, question: str, context: str = "") -> str:
        clean = _strip_rag_metadata(context) if context else ""
        normalized_context = clean if clean else "(Bağlam bulunamadı)"
        return USER_PROMPT_TEMPLATE.format(context=normalized_context, question=question)

    def generate(self, question: str, context: str = "") -> dict:
        """Generate a response using Ollama LLM."""
        start_time = time.time()

        if not context or not context.strip():
            return {"answer": NO_CONTEXT_FALLBACK_MESSAGE, "model": self.model}

        user_prompt = self._build_user_prompt(question, context)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "top_p": 0.9,
                            "num_predict": 600,
                            "repeat_penalty": 1.1,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                answer = data.get("message", {}).get("content", "").strip()
                elapsed_ms = int((time.time() - start_time) * 1000)

                if not answer:
                    answer = NO_CONTEXT_FALLBACK_MESSAGE
                else:
                    answer = _clean_answer(answer)

                logger.info(f"LLM generated response in {elapsed_ms}ms")
                return {"answer": answer, "model": self.model, "response_time_ms": elapsed_ms}

        except httpx.TimeoutException:
            logger.error("LLM request timed out")
            return {
                "answer": "Yanıt süresi aşıldı. Lütfen tekrar deneyin.",
                "model": self.model,
            }
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return {"answer": NO_CONTEXT_FALLBACK_MESSAGE, "model": self.model}

    def generate_stream(self, question: str, context: str = "") -> Generator[str, None, None]:
        """Stream response from Ollama using Server-Sent Events."""
        if not context or not context.strip():
            yield json.dumps({"content": NO_CONTEXT_FALLBACK_MESSAGE, "done": False})
            yield json.dumps({"content": "", "done": True})
            return

        user_prompt = self._build_user_prompt(question, context)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": True,
                        "options": {
                            "temperature": 0.1,
                            "top_p": 0.9,
                            "num_predict": 600,
                            "repeat_penalty": 1.1,
                        },
                    },
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            done = data.get("done", False)
                            yield json.dumps({"content": content, "done": done})
                            if done:
                                break
                        except json.JSONDecodeError:
                            continue

        except httpx.TimeoutException:
            logger.error("LLM streaming timed out")
            yield json.dumps({"content": "Yanıt süresi aşıldı. Lütfen tekrar deneyin.", "done": False})
            yield json.dumps({"content": "", "done": True})
        except Exception as e:
            logger.error(f"LLM streaming failed: {e}")
            yield json.dumps({"content": NO_CONTEXT_FALLBACK_MESSAGE, "done": False})
            yield json.dumps({"content": "", "done": True})

    def get_embedding(self, text: str) -> list[float] | None:
        """Get embedding vector for a text using Ollama."""
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
                # Try newer endpoint first
                response = client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": settings.EMBEDDING_MODEL, "input": text},
                )

                if response.status_code == 404:
                    response = client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": settings.EMBEDDING_MODEL, "prompt": text},
                    )

                response.raise_for_status()
                data = response.json()

                embeddings = data.get("embeddings")
                if embeddings:
                    return embeddings[0]

                legacy_embedding = data.get("embedding")
                if legacy_embedding:
                    return legacy_embedding

                return None
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Get embeddings for multiple texts."""
        return [self.get_embedding(text) for text in texts]

    def no_context_result(self) -> dict:
        """Return a fallback when no retrievable context exists."""
        return {"answer": NO_CONTEXT_FALLBACK_MESSAGE}


# Module-level singleton
llm_service = LLMService()
