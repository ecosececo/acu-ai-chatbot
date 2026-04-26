"""
LLM Service — Communicates with Ollama to generate AI responses.
Handles prompt engineering, streaming, language detection, and error handling.
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

# ── Fallback messages ─────────────────────────────────────────────────────────

NO_CONTEXT_FALLBACK_MESSAGE = (
    "Bu konuda yeterli bilgi bulunamadı. Lütfen sorunuzu farklı şekilde sormayı deneyin."
)
NO_CONTEXT_FALLBACK_MESSAGE_EN = (
    "No information was found on this topic. Please try rephrasing your question."
)

# ── System prompts ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Sen Acıbadem Üniversitesi için bir bilgi asistanısın.
Sana verilen BAĞLAM METNİNDEN soruyu yanıtla.

KURAL 1: Yanıtında YALNIZCA bağlam metnindeki bilgileri kullan. Bağlamda olmayan bilgi ekleme.
KURAL 2: Bağlamda cevap yoksa sadece şunu yaz: "Bu konuda bilgi bulunamadı."
KURAL 3: SADECE TÜRKÇE yaz. İngilizce, Japonca, Çince veya başka dil kesinlikle kullanma. Kısa ve net cümleler kur. Doğrudan yanıta başla.
KURAL 4: Kısaltmaları (ÖSYM, YKS, TUS, TTO vb.) bağlamda açıkça yazılmadıkça kendin açıklama.
KURAL 5: Bölüm sorusuna fakülte listesiyle, fakülte sorusuna bölüm listesiyle yanıt verme.
KURAL 6: Bağlamdaki bilgi yalnızca tek bir bölüme veya programa aitse, bunu yanıtında belirt.
KURAL 7: Bağlamdaki etkinlik, haber veya duyuru içeriklerini genel üniversite politikası olarak aktarma.
KURAL 8: Partner üniversite veya ülke isimlerini YALNIZCA bağlamda kelimesi kelimesine yazılı olanları yaz. Bağlamda "Avrupa ülkeleri" gibi genel bir ifade varsa tek tek ülke sayma. Bağlamda partner üniversite yoksa şunu yaz: "Partner üniversiteler hakkında detaylı bilgi mevcut kaynaklarda yer almamaktadır."
KURAL 9: Erasmus veya değişim programı genel sorularında kısa yanıt ver; partner üniversite, ülke, bölüm veya koordinatör listesi verme, kullanıcı açıkça istemedikçe bunları ekleme.
KURAL 10: Bağlam kısıtlıysa KISA yanıt ver. Örnekle genişletme, bağlamda olmayan detay ekleme.
KURAL 11: Bölüm başkanı, koordinatör, müdür, dekan gibi değişebilecek görev/pozisyon bilgilerini aktarırken "Mevcut kaynaklara göre ... olarak belirtilmektedir" gibi temkinli ifade kullan."""

SYSTEM_PROMPT_EN = """You are a knowledge assistant for Acıbadem University.
Answer the question using ONLY the CONTEXT TEXT provided below.
The context may be in Turkish — read and understand it, then write your answer in English.

RULE 1: Use ONLY information from the context. Do not add knowledge not present in the context.
RULE 2: If the answer is not in the context, write only: "No information found on this topic."
RULE 3: Write ONLY IN ENGLISH. Short, clear sentences. Start directly with the answer.
RULE 4: Do NOT expand abbreviations (ÖSYM, YKS, TUS, etc.) unless the full form appears in the context.
RULE 5: Do not answer a departments question with a faculties list, or vice versa.
RULE 6: If context covers only one specific department or program, note it in your answer.
RULE 7: Do not treat event announcements or news items as general university policy.
RULE 8: List partner universities or countries ONLY if they are named word-for-word in the context. If context says "European countries" do NOT expand that into individual country names. If no partner universities appear in the context, write: "Detailed information about partner universities is not available in the current sources."
RULE 9: For general Erasmus or exchange-program questions, answer briefly. Do not include partner universities, countries, departments, or coordinators unless the user explicitly asks for them.
RULE 10: When context is limited, give a SHORT answer. Do not add examples or details not present in the context.
RULE 11: For dynamic role or position facts such as department head, coordinator, director, or dean, use cautious phrasing such as "According to the available sources, ... is listed as ..."."""

# ── User prompt templates ─────────────────────────────────────────────────────

USER_PROMPT_TEMPLATE = """BAĞLAM (Acıbadem Üniversitesi resmi sitesinden alınan bilgiler):
{context}

SORU: {question}

Yukarıdaki BAĞLAM metnini kullanarak soruyu yanıtla. Bağlam dışı bilgi ekleme.
ÖNEMLİ: Bağlamda "Hayır" veya "değildir" varsa bunu koru. Kendi bilgini kullanma.
ÖNEMLİ: Üniversite veya ülke listesi verirken YALNIZCA bağlamda geçenleri yaz, kendi bilginden ekleme yapma.
ÖNEMLİ: Görev/pozisyon bilgileri için kesin konuşma; "Mevcut kaynaklara göre" tarzı ifade kullan.
Yanıt:"""

USER_PROMPT_TEMPLATE_EN = """CONTEXT (from Acıbadem University official sources):
{context}

Turkish term guide: "bölüm/bölümler"=department/departments, "fakülte/fakülteler"=faculty/faculties,
"ders/dersler/müfredat/ders programı"=course/courses/curriculum, "yıl"=year, "dönem"=semester,
"lisans"=undergraduate, "başvuru"=application, "burs"=scholarship,
"iletişim"=contact, "kampüs"=campus, "adres"=address, "nerede"=where.

QUESTION: {question}

Answer the question using the context above. Do not add information outside the context.
IMPORTANT: If the context says something is not available, preserve that. Do not use your own knowledge.
IMPORTANT: When listing universities or countries, include ONLY those named in the context. Do not add more from your own knowledge.
IMPORTANT: For role or position information, avoid absolute wording; use "According to the available sources" style phrasing.
Answer:"""

# ── Helpers ───────────────────────────────────────────────────────────────────

_NOISE_PREFIXES = re.compile(
    r"^(kısa cevap|short answer|cevap|yanıt|özet|answer|response|summary)\s*[:：]\s*",
    re.IGNORECASE,
)

_TURKISH_CHARS = frozenset("ışğüöçİŞĞÜÖÇı")

_NON_TURKISH_BLOCK = re.compile(
    r"[⺀-鿿豈-﫿︰-﹏＀-￯　-〿]+"
)


def _detect_language(text: str) -> str:
    """Detect the answer language from the user's wording."""
    words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    english_markers = {
        "who", "what", "where", "when", "which", "how", "why", "is", "are",
        "does", "do", "can", "tell", "about", "located", "department",
    }
    turkish_ascii_markers = {
        "hangi", "hangileri", "kac", "kaç", "varmi", "fakulte", "fakultesi",
        "bolum", "bolumler", "hakkinda", "basvuru", "ogrenci", "kampus",
    }
    if words & english_markers:
        return "en"
    if any(c in _TURKISH_CHARS for c in text):
        return "tr"
    if words & turkish_ascii_markers:
        return "tr"
    return "en"


def _strip_rag_metadata(context: str) -> str:
    """Remove RAG metadata and markdown heading markers from context before sending to LLM."""
    lines = []
    for line in context.splitlines():
        stripped = line.strip()
        if stripped.startswith("### Kaynak"):
            continue
        if stripped.startswith("URL:"):
            continue
        if stripped.startswith("Benzerlik Skoru:"):
            continue
        if stripped == "---":
            lines.append("")
            continue
        cleaned_line = re.sub(r"^#{1,4}\s+", "", line.strip())
        lines.append(cleaned_line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


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


def _soften_dynamic_role_answer(text: str, lang: str) -> str:
    """Use cautious wording for facts about roles that may change over time."""
    lowered = text.lower()
    if lang == "en":
        role_terms = ("department head", "coordinator", "director", "dean", "chair")
        if not any(term in lowered[:140] for term in role_terms):
            return text
        text = re.sub(r",?\s*according to (the )?available sources\.?$", ".", text, flags=re.IGNORECASE).strip()
        if not text.lower().startswith("according to the available sources"):
            return f"According to the available sources, {text[0].lower() + text[1:] if text else text}"
        return text

    role_terms = ("bölüm başkanı", "bölümü başkanı", "başkanı", "koordinatör", "müdür", "dekan")
    if not any(term in lowered[:140] for term in role_terms):
        return text
    text = re.sub(r",?\s*mevcut kaynaklara göre\.?$", ".", text, flags=re.IGNORECASE).strip()
    if not text.lower().startswith("mevcut kaynaklara göre"):
        return f"Mevcut kaynaklara göre {text}"
    return text


# ── LLMService ────────────────────────────────────────────────────────────────


class LLMService:
    """Handles all communication with the Ollama LLM service."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.LLM_MODEL
        self.keep_alive = getattr(settings, "OLLAMA_KEEP_ALIVE", "5m")
        self.timeout = httpx.Timeout(timeout=40.0, connect=10.0)

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

    def _build_prompt(self, question: str, context: str, lang: str) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) for the detected language."""
        clean = _strip_rag_metadata(context) if context else ""
        if lang == "en":
            normalized_context = clean if clean else "(No context found)"
            user_prompt = USER_PROMPT_TEMPLATE_EN.format(
                context=normalized_context, question=question
            )
            return SYSTEM_PROMPT_EN, user_prompt
        else:
            normalized_context = clean if clean else "(Bağlam bulunamadı)"
            user_prompt = USER_PROMPT_TEMPLATE.format(
                context=normalized_context, question=question
            )
            return SYSTEM_PROMPT, user_prompt

    def generate(self, question: str, context: str = "") -> dict:
        """Generate a response using Ollama LLM."""
        start_time = time.time()
        lang = _detect_language(question)
        fallback = NO_CONTEXT_FALLBACK_MESSAGE_EN if lang == "en" else NO_CONTEXT_FALLBACK_MESSAGE

        if not context or not context.strip():
            return {"answer": fallback, "model": self.model}

        system_prompt, user_prompt = self._build_prompt(question, context, lang)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                        "keep_alive": self.keep_alive,
                        "options": {
                            "temperature": 0,
                            "top_p": 0.9,
                            "num_predict": 360,
                            "repeat_penalty": 1.1,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                answer = data.get("message", {}).get("content", "").strip()
                elapsed_ms = int((time.time() - start_time) * 1000)

                if not answer:
                    answer = fallback
                else:
                    answer = _clean_answer(answer)
                    answer = _soften_dynamic_role_answer(answer, lang)

                logger.info(f"LLM generated response in {elapsed_ms}ms (lang={lang})")
                return {"answer": answer, "model": self.model, "response_time_ms": elapsed_ms}

        except httpx.TimeoutException:
            logger.error("LLM request timed out")
            timeout_msg = (
                "Request timed out. Please try again."
                if lang == "en"
                else "Yanıt süresi aşıldı. Lütfen tekrar deneyin."
            )
            return {"answer": timeout_msg, "model": self.model}
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return {"answer": fallback, "model": self.model}

    def generate_stream(self, question: str, context: str = "") -> Generator[str, None, None]:
        """Stream response from Ollama using Server-Sent Events."""
        lang = _detect_language(question)
        fallback = NO_CONTEXT_FALLBACK_MESSAGE_EN if lang == "en" else NO_CONTEXT_FALLBACK_MESSAGE

        if not context or not context.strip():
            yield json.dumps({"content": fallback, "done": False})
            yield json.dumps({"content": "", "done": True})
            return

        system_prompt, user_prompt = self._build_prompt(question, context, lang)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": True,
                        "keep_alive": self.keep_alive,
                        "options": {
                            "temperature": 0,
                            "top_p": 0.9,
                            "num_predict": 360,
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
            timeout_msg = (
                "Request timed out. Please try again."
                if lang == "en"
                else "Yanıt süresi aşıldı. Lütfen tekrar deneyin."
            )
            yield json.dumps({"content": timeout_msg, "done": False})
            yield json.dumps({"content": "", "done": True})
        except Exception as e:
            logger.error(f"LLM streaming failed: {e}")
            yield json.dumps({"content": fallback, "done": False})
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
