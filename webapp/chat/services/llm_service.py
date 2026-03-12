"""
LLM Service — Communicates with Ollama to generate AI responses.
Handles prompt engineering, streaming, and error handling.
"""

import json
import logging
import time
from typing import Generator

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ── System Prompt ────────────────────────────────────────
SYSTEM_PROMPT = """Sen Acıbadem Üniversitesi'nin resmi AI asistanısın. Adın "ACU Asistan".

## Görevin
Acıbadem Üniversitesi hakkında sorulan sorulara doğru, güncel ve faydalı yanıtlar vermek.

## Kurallar
1. **YALNIZCA** sana sağlanan bağlam (context) bilgilerine dayanarak cevap ver.
2. Bağlamda bulunmayan bilgileri **UYDURMA**. Bilmiyorsan "Bu konuda elimde yeterli bilgi yok, lütfen üniversitenin resmi web sitesini ziyaret edin: https://www.acibadem.edu.tr" de.
3. Yanıtlarını **Türkçe** ver (kullanıcı İngilizce sorarsa İngilizce yanıt ver).
4. Yanıtların açık, düzenli ve anlaşılır olsun. Gerektiğinde madde işaretleri ve başlıklar kullan.
5. Akademik programlar, dersler, kredi bilgileri gibi detayları doğru ver.
6. Kibarlığını koru ve yardımsever ol.
7. Kaynakları belirt — hangi sayfadan bilgi aldığını söyle.

## Acıbadem Üniversitesi Hakkında Genel Bilgi
- Acıbadem Üniversitesi, İstanbul'da bulunan bir vakıf üniversitesidir.
- Sağlık bilimleri alanında güçlü bir üniversitedir.
- Ana kampüsü Ataşehir/Kerem Aydınlar Kampüsü'dür.
- Web sitesi: https://www.acibadem.edu.tr
- Bologna sistemi: https://obs.acibadem.edu.tr

## Yanıt Formatı
- Kısa ve öz yanıtlar ver.
- Gerektiğinde detaylı açıklama yap.
- Listeleme gerektiren yanıtlarda madde işaretleri kullan.
- Linkleri paylaş.
"""

USER_PROMPT_TEMPLATE = """## Sağlanan Bağlam (Context)
Aşağıdaki bilgiler Acıbadem Üniversitesi'nin resmi web sitelerinden alınmıştır:

{context}

## Kullanıcı Sorusu
{question}

## Talimat
Yukarıdaki bağlam bilgilerini kullanarak kullanıcının sorusunu yanıtla. Bağlamda yoksa bilgiyi uydurma."""


class LLMService:
    """Handles all communication with the Ollama LLM service."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.LLM_MODEL
        self.timeout = httpx.Timeout(timeout=300.0, connect=10.0)

    def is_available(self) -> bool:
        """Check if Ollama service is running and model is available."""
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
                    # Match full name or base name
                    available = (
                        self.model in model_names
                        or any(self.model.split(":")[0] == n.split(":")[0] for n in model_names)
                    )
                    cache.set(cache_key, available, timeout=30)
                    return available
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            cache.set(cache_key, False, timeout=10)
            return False

    def generate(self, question: str, context: str = "") -> dict:
        """
        Generate a response from the LLM.

        Returns:
            dict with keys: answer, model, response_time_ms
        """
        start_time = time.time()

        if not context:
            user_prompt = question
        else:
            user_prompt = USER_PROMPT_TEMPLATE.format(
                context=context,
                question=question,
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": 0.4,
                "top_p": 0.9,
                "num_predict": 512,
                "repeat_penalty": 1.3,
                "repeat_last_n": 128,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            elapsed_ms = int((time.time() - start_time) * 1000)

            return {
                "answer": data.get("message", {}).get("content", ""),
                "model": data.get("model", self.model),
                "response_time_ms": elapsed_ms,
            }

        except httpx.TimeoutException:
            logger.error("LLM request timed out")
            return {
                "answer": "Üzgünüm, AI modeli şu anda yanıt vermekte zorlanıyor. Lütfen daha sonra tekrar deneyin.",
                "model": self.model,
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": True,
            }
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return {
                "answer": "Bir hata oluştu. AI servisi şu anda kullanılamıyor olabilir. Lütfen daha sonra tekrar deneyin.",
                "model": self.model,
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": True,
            }

    def generate_stream(self, question: str, context: str = "") -> Generator[str, None, None]:
        """
        Stream a response from the LLM token by token.

        Yields:
            JSON strings with partial content
        """
        if not context:
            user_prompt = question
        else:
            user_prompt = USER_PROMPT_TEMPLATE.format(
                context=context,
                question=question,
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": True,
            "options": {
                "temperature": 0.4,
                "top_p": 0.9,
                "num_predict": 512,
                "repeat_penalty": 1.3,
                "repeat_last_n": 128,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                content = data.get("message", {}).get("content", "")
                                if content:
                                    yield json.dumps({"content": content, "done": False})
                                if data.get("done"):
                                    yield json.dumps({"content": "", "done": True})
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error(f"LLM streaming failed: {e}")
            yield json.dumps({
                "content": "Bir hata oluştu. Lütfen tekrar deneyin.",
                "done": True,
                "error": True,
            })

    def get_embedding(self, text: str) -> list[float] | None:
        """Get embedding vector for a text using Ollama."""
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
                response = client.post(
                    f"{self.base_url}/api/embed",
                    json={
                        "model": settings.EMBEDDING_MODEL,
                        "input": text,
                    },
                )
                response.raise_for_status()
                data = response.json()
                embeddings = data.get("embeddings", [])
                if embeddings:
                    return embeddings[0]
                return None
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Get embeddings for multiple texts."""
        results = []
        for text in texts:
            results.append(self.get_embedding(text))
        return results


# Module-level singleton
llm_service = LLMService()
