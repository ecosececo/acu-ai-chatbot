"""
LLM Service — Communicates with the configured LLM provider.
Handles prompt engineering, streaming, and error handling.
"""

import json
import logging
import time
from typing import Generator

_LLM_MAX_RETRIES = 1

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ── System Prompt ────────────────────────────────────────
SYSTEM_PROMPT = """Sen Acıbadem Üniversitesi asistanısın. SADECE sağlanan bağlamdaki bilgileri kullanarak Türkçe yanıt ver.
Bağlamda yoksa "Bu bilgi elimde yok." de.
Ders listesi istendiğinde ders kodlarını ve Türkçe adlarını AYNEN yaz, İngilizceye çevirme.
Ücretleri TL cinsinden ver; USD sadece "uluslararası öğrenci" sorulduğunda."""

USER_PROMPT_TEMPLATE = """Bağlam:
{context}

---

{history_section}Soru: {question}"""




class LLMService:
    """Handles all communication with the configured LLM service."""

    def __init__(self):
        self.provider = getattr(settings, "LLM_PROVIDER", "ollama").lower()
        self.ollama_base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.tgi_base_url = getattr(settings, "TGI_BASE_URL", "").rstrip("/")
        self.groq_api_key = getattr(settings, "GROQ_API_KEY", "")
        self.groq_base_url = getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
        self.model = settings.LLM_MODEL
        self.timeout = httpx.Timeout(timeout=300.0, connect=10.0)

    def is_available(self) -> bool:
        """Check if the configured LLM service is running and available."""
        cache_key = f"llm_available:{self.provider}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
                if self.provider == "tgi":
                    if not self.tgi_base_url:
                        cache.set(cache_key, False, timeout=10)
                        return False
                    response = client.get(f"{self.tgi_base_url}/health")
                    available = response.status_code == 200
                    cache.set(cache_key, available, timeout=15)
                    return available

                if self.provider == "groq":
                    available = bool(self.groq_api_key)
                    cache.set(cache_key, available, timeout=60)
                    return available

                if self.provider != "ollama":
                    logger.warning(f"Unknown LLM provider: {self.provider}")
                    cache.set(cache_key, False, timeout=10)
                    return False

                response = client.get(f"{self.ollama_base_url}/api/tags")
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
            logger.warning(f"LLM health check failed ({self.provider}): {e}")
            cache.set(cache_key, False, timeout=10)
            return False

        cache.set(cache_key, False, timeout=10)
        return False

    def _build_user_prompt(
        self, question: str, context: str = "", history: list[dict] | None = None
    ) -> str:
        """Build user prompt with optional context and conversation history."""
        if not context:
            context = "Veritabanında bu soruyla ilgili spesifik bir bilgi bulunamadı."

        # Build history section
        history_section = ""
        if history:
            history_lines = []
            for msg in history[-6:]:  # Last 6 messages (3 exchanges max)
                role_label = "Kullanıcı" if msg["role"] == "user" else "Asistan"
                # Truncate long messages in history
                content = msg["content"][:300]
                if len(msg["content"]) > 300:
                    content += "..."
                history_lines.append(f"**{role_label}:** {content}")
            history_section = (
                "## Önceki Sohbet Geçmişi\n"
                + "\n".join(history_lines)
                + "\n\n"
            )

        return USER_PROMPT_TEMPLATE.format(
            context=context,
            question=question,
            history_section=history_section,
        )

    def generate(
        self, question: str, context: str = "", history: list[dict] | None = None
    ) -> dict:
        """
        Generate a response from the LLM.

        Args:
            question: User's question
            context: RAG context string
            history: List of previous messages [{"role": "user/assistant", "content": "..."}]

        Returns:
            dict with keys: answer, model, response_time_ms
        """
        start_time = time.time()

        if self.provider == "tgi":
            return self._generate_tgi(question, context, history, start_time)

        if self.provider == "groq":
            return self._generate_groq(question, context, history, start_time)

        return self._generate_ollama(question, context, history, start_time)

    def generate_stream(
        self, question: str, context: str = "", history: list[dict] | None = None
    ) -> Generator[str, None, None]:
        """
        Stream a response from the LLM token by token.

        Args:
            question: User's question
            context: RAG context string
            history: List of previous messages [{"role": "user/assistant", "content": "..."}]

        Yields:
            JSON strings with partial content
        """
        if self.provider == "tgi":
            yield from self._generate_stream_tgi(question, context, history)
            return

        if self.provider == "groq":
            yield from self._generate_stream_groq(question, context, history)
            return

        yield from self._generate_stream_ollama(question, context, history)


    def get_embedding(self, text: str) -> list[float] | None:
        """Get embedding vector for a text using Ollama."""
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
                response = client.post(
                    f"{self.ollama_base_url}/api/embed",
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

    def _generate_ollama(
        self, question: str, context: str, history: list[dict] | None, start_time: float
    ) -> dict:
        user_prompt = self._build_user_prompt(question, context, history)
        if any(term in question.lower() for term in ("ders", "ders program", "dersler", "mufredat", "müfredat")):
            user_prompt = (
                "DERS PROGRAMI TALIMATI: Oncelikle ONCELIKLI DERS PROGRAMI TABLOSU bolumunu kullan. "
                "Soruyu tabloya gore yorumla. Tam ders listesi istenirse yariyil basliklari altinda dersleri listele. "
                "Soru 'nasil' gibi genel sorulduysa her yariyili 1-2 cumleyle ozetle; tum dersleri tek tek dokme. "
                "Tabloda olmayan ders, saat, AKTS veya genel universite bilgisi uydurma. Ic muhakemeyi gosterme.\n\n"
                + user_prompt
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": "Ders programi sorularinda oncelikli ders tablosunu esas al. Soruya gore tabloyu ozetle, karsilastir veya listele; baglam disi bilgi uydurma ve ic muhakemeyi gosterme."},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "num_predict": 1024,
                "num_ctx": 4096,
                "num_batch": 256,
                "repeat_penalty": 1.3,
                "repeat_last_n": 64,
                "num_gpu": settings.OLLAMA_NUM_GPU,
            },
        }

        for attempt in range(_LLM_MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        f"{self.ollama_base_url}/api/chat",
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
            except httpx.ConnectError as e:
                if attempt < _LLM_MAX_RETRIES:
                    logger.warning(f"LLM connect error (attempt {attempt + 1}), retrying: {e}")
                    time.sleep(1)
                    continue
                logger.error(f"LLM connection failed after retries: {e}")
                return {
                    "answer": "AI servisine bağlanılamadı. Lütfen daha sonra tekrar deneyin.",
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

    def _generate_tgi(
        self, question: str, context: str, history: list[dict] | None, start_time: float
    ) -> dict:
        if not self.tgi_base_url:
            return {
                "answer": "AI servisi yapılandırılmamış. Lütfen daha sonra tekrar deneyin.",
                "model": self.model,
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": True,
            }

        user_prompt = self._build_user_prompt(question, context, history)
        # TGI's OpenAI-compatible endpoint applies the model's chat template
        # automatically — much safer than building a raw prompt string.
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": "Ders programi sorularinda oncelikli ders tablosunu esas al. Soruya gore tabloyu ozetle, karsilastir veya listele; baglam disi bilgi uydurma ve ic muhakemeyi gosterme."},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "top_p": 0.85,
            "max_tokens": 1024,
            "repetition_penalty": 1.3,
            "stream": False,
        }

        for attempt in range(_LLM_MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        f"{self.tgi_base_url}/v1/chat/completions",
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                elapsed_ms = int((time.time() - start_time) * 1000)
                answer = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                return {
                    "answer": answer,
                    "model": self.model,
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
            except httpx.ConnectError as e:
                if attempt < _LLM_MAX_RETRIES:
                    logger.warning(f"LLM connect error (attempt {attempt + 1}), retrying: {e}")
                    time.sleep(1)
                    continue
                logger.error(f"LLM connection failed after retries: {e}")
                return {
                    "answer": "AI servisine bağlanılamadı. Lütfen daha sonra tekrar deneyin.",
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

    def _generate_groq(
        self, question: str, context: str, history: list[dict] | None, start_time: float
    ) -> dict:
        if not self.groq_api_key:
            return {
                "answer": "Groq API anahtarı yapılandırılmamış. Lütfen yönetici ile iletişime geçin.",
                "model": self.model,
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": True,
            }

        user_prompt = self._build_user_prompt(question, context, history)
        headers = {"Authorization": f"Bearer {self.groq_api_key}"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "top_p": 0.85,
            "max_tokens": 1024,
            "stream": False,
        }

        for attempt in range(_LLM_MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        f"{self.groq_base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()
                    data = response.json()

                elapsed_ms = int((time.time() - start_time) * 1000)
                answer = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                return {
                    "answer": answer,
                    "model": self.model,
                    "response_time_ms": elapsed_ms,
                }

            except httpx.TimeoutException:
                logger.error("Groq request timed out")
                return {
                    "answer": "Üzgünüm, AI modeli şu anda yanıt vermekte zorlanıyor. Lütfen daha sonra tekrar deneyin.",
                    "model": self.model,
                    "response_time_ms": int((time.time() - start_time) * 1000),
                    "error": True,
                }
            except httpx.ConnectError as e:
                if attempt < _LLM_MAX_RETRIES:
                    logger.warning(f"Groq connect error (attempt {attempt + 1}), retrying: {e}")
                    time.sleep(1)
                    continue
                logger.error(f"Groq connection failed after retries: {e}")
                return {
                    "answer": "AI servisine bağlanılamadı. Lütfen daha sonra tekrar deneyin.",
                    "model": self.model,
                    "response_time_ms": int((time.time() - start_time) * 1000),
                    "error": True,
                }
            except Exception as e:
                logger.error(f"Groq generation failed: {e}")
                return {
                    "answer": "Bir hata oluştu. AI servisi şu anda kullanılamıyor olabilir.",
                    "model": self.model,
                    "response_time_ms": int((time.time() - start_time) * 1000),
                    "error": True,
                }

    def _generate_stream_groq(
        self, question: str, context: str, history: list[dict] | None
    ) -> Generator[str, None, None]:
        if not self.groq_api_key:
            yield json.dumps({
                "content": "Groq API anahtarı yapılandırılmamış.",
                "done": True,
                "error": True,
            })
            return

        user_prompt = self._build_user_prompt(question, context, history)
        headers = {"Authorization": f"Bearer {self.groq_api_key}"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "top_p": 0.85,
            "max_tokens": 1024,
            "stream": True,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.groq_base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        if isinstance(line, bytes):
                            line = line.decode("utf-8", errors="ignore")
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if line == "[DONE]":
                            yield json.dumps({"content": "", "done": True})
                            break
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        content = (
                            data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if content:
                            yield json.dumps({"content": content, "done": False})
        except Exception as e:
            logger.error(f"Groq streaming failed: {e}")
            yield json.dumps({
                "content": "Bir hata oluştu. Lütfen tekrar deneyin.",
                "done": True,
                "error": True,
            })

    def _generate_stream_ollama(
        self, question: str, context: str, history: list[dict] | None
    ) -> Generator[str, None, None]:
        user_prompt = self._build_user_prompt(question, context, history)
        if any(term in question.lower() for term in ("ders", "ders program", "dersler", "mufredat", "müfredat")):
            user_prompt = (
                "DERS PROGRAMI TALIMATI: Oncelikle ONCELIKLI DERS PROGRAMI TABLOSU bolumunu kullan. "
                "Soruyu tabloya gore yorumla. Tam ders listesi istenirse yariyil basliklari altinda dersleri listele. "
                "Soru 'nasil' gibi genel sorulduysa her yariyili 1-2 cumleyle ozetle; tum dersleri tek tek dokme. "
                "Tabloda olmayan ders, saat, AKTS veya genel universite bilgisi uydurma. Ic muhakemeyi gosterme.\n\n"
                + user_prompt
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": "Ders programi sorularinda oncelikli ders tablosunu esas al. Soruya gore tabloyu ozetle, karsilastir veya listele; baglam disi bilgi uydurma ve ic muhakemeyi gosterme."},
                {"role": "user", "content": user_prompt},
            ],
            "stream": True,
            "think": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "num_predict": 1024,
                "num_ctx": 4096,
                "num_batch": 256,
                "repeat_penalty": 1.3,
                "repeat_last_n": 64,
                "num_gpu": settings.OLLAMA_NUM_GPU,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.ollama_base_url}/api/chat",
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

    def _generate_stream_tgi(
        self, question: str, context: str, history: list[dict] | None
    ) -> Generator[str, None, None]:
        if not self.tgi_base_url:
            yield json.dumps({
                "content": "AI servisi yapılandırılmamış. Lütfen tekrar deneyin.",
                "done": True,
                "error": True,
            })
            return

        user_prompt = self._build_user_prompt(question, context, history)
        # Use TGI's OpenAI-compatible streaming endpoint — chat template applied automatically.
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "top_p": 0.85,
            "max_tokens": 1024,
            "repetition_penalty": 1.3,
            "stream": True,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.tgi_base_url}/v1/chat/completions",
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        if isinstance(line, bytes):
                            line = line.decode("utf-8", errors="ignore")
                        # OpenAI SSE format: "data: {...}" or "data: [DONE]"
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if line == "[DONE]":
                            yield json.dumps({"content": "", "done": True})
                            break
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        content = (
                            data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if content:
                            yield json.dumps({"content": content, "done": False})
        except Exception as e:
            logger.error(f"LLM streaming failed: {e}")
            yield json.dumps({
                "content": "Bir hata oluştu. Lütfen tekrar deneyin.",
                "done": True,
                "error": True,
            })


# Module-level singleton
llm_service = LLMService()
