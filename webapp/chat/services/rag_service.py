"""
RAG Service — Retrieval-Augmented Generation using pgvector.
Handles document chunking, embedding storage, and semantic search.
"""

import hashlib
import logging
import re
from typing import Optional

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.cache import cache
from django.db import connection
from django.db.models import Q
from django.db.models.functions import Length
from pgvector.django import CosineDistance

from ..models import DocumentChunk, WebPage
from .llm_service import llm_service

_EMBEDDING_CACHE_TTL = 3600  # 1 hour


def _get_cached_embedding(text: str) -> list[float] | None:
    """Return cached embedding or call Ollama and cache the result."""
    key = "qemb:" + hashlib.md5(text.encode("utf-8")).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    embedding = llm_service.get_embedding(text)
    if embedding is not None:
        cache.set(key, embedding, timeout=_EMBEDDING_CACHE_TTL)
    return embedding

logger = logging.getLogger(__name__)

TR_CHAR_TRANSLATION = str.maketrans({
    "ı": "i",
    "İ": "i",
    "ş": "s",
    "Ş": "s",
    "ğ": "g",
    "Ğ": "g",
    "ü": "u",
    "Ü": "u",
    "ö": "o",
    "Ö": "o",
    "ç": "c",
    "Ç": "c",
})

QUERY_EXPANSIONS = {
    "bilgisayar muhendisligi": [
        "computer engineering",
        "bilgisayar",
        "muhendislik",
        "computer",
        "engineering",
    ],
    "yazilim muhendisligi": [
        "software engineering",
        "yazilim",
        "muhendislik",
        "software",
        "engineering",
    ],
    "tip fakultesi": ["medicine", "medical", "tip"],
    "eczacilik": ["pharmacy", "pharmaceutical"],
    "muhendislik bolumleri": [
        "muhendislik fakultesi",
        "bilgisayar muhendisligi",
        "yazilim muhendisligi",
        "biyomedikal muhendisligi",
        "endustri muhendisligi",
        "bolumler",
    ],
    "kampus nerede": ["adres", "yerleske", "iletisim", "konum", "istanbul"],
    "ne zaman kuruldu": ["kurulus", "kuruldu", "tarihce", "hakkimizda"],
}

# Maps English phrases to Turkish retrieval terms. Longer phrases listed first
# so phrase matching skips redundant sub-phrase matches (e.g. "computer engineering"
# is matched before the standalone "engineering" key covers the same span).
EN_TO_TR_QUERY_MAP: dict[str, list[str]] = {
    # ── Specific departments / programs ──────────────────────────
    "computer engineering":   ["bilgisayar mühendisliği", "bilgisayar"],
    "software engineering":   ["yazılım mühendisliği", "yazılım"],
    "biomedical engineering": ["biyomedikal mühendisliği", "biyomedikal"],
    "molecular biology":      ["moleküler biyoloji", "genetik"],
    "health sciences":        ["sağlık bilimleri"],
    "physical therapy":       ["fizyoterapi rehabilitasyon"],
    "physiotherapy":          ["fizyoterapi rehabilitasyon"],
    "nursing":                ["hemşirelik"],
    "pharmacy":               ["eczacılık"],
    "medicine":               ["tıp"],
    "medical":                ["tıp"],
    "nutrition":              ["beslenme diyetetik"],
    "dietetics":              ["diyetetik"],
    "psychology":             ["psikoloji"],
    "sociology":              ["sosyoloji"],
    "engineering":            ["mühendislik"],
    # ── Faculty / structure ───────────────────────────────────────
    "faculty of medicine":    ["tıp fakültesi"],
    "medicine faculty":       ["tıp fakültesi"],
    "engineering faculty":    ["mühendislik fakültesi", "mühendislik"],
    "international students": ["uluslararası öğrenci", "uluslararası"],
    "international":          ["uluslararası"],
    "faculties":              ["fakülteler", "fakülte"],
    "faculty":                ["fakülte"],
    "departments":            ["bölümler", "bölüm"],
    "department":             ["bölüm"],
    "programs":               ["programlar", "program"],
    "curriculum":             ["müfredat", "ders"],
    "courses":                ["dersler", "ders", "müfredat"],
    "undergraduate":          ["lisans"],
    "graduate":               ["lisansüstü", "yüksek lisans"],
    "scholarship":            ["burs"],
    # ── Actions / intent ─────────────────────────────────────────
    "what faculties":         ["hangi fakülteler", "fakülteler"],
    "what departments":       ["hangi bölümler", "bölümler"],
    "what programs":          ["hangi programlar", "programlar"],
    "how many faculties":     ["kaç fakülte", "fakülteler"],
    "how can i apply":        ["nasıl başvurulur", "başvuru", "kayıt"],
    "how to apply":           ["nasıl başvurulur", "başvuru", "kayıt"],
    "is there":               ["var", "mevcut"],
    "are there":              ["var", "mevcut"],
    "apply":                  ["başvuru", "kayıt"],
    "application":            ["başvuru"],
    "admission":              ["kabul", "başvuru", "kayıt"],
    "registration":           ["kayıt"],
    # ── Location / contact ───────────────────────────────────────
    "contact details":        ["iletişim bilgileri", "telefon", "adres"],
    "where is":               ["nerede", "adres", "kampüs"],
    "located":                ["nerede", "adres", "kampüs", "İstanbul"],
    "location":               ["adres", "kampüs", "konum"],
    "contact":                ["iletişim", "telefon", "adres"],
    "address":                ["adres", "iletişim"],
    "campus":                 ["kampüs", "Atakent"],
    # ── Founding / general info ──────────────────────────────────
    "when was":               ["ne zaman", "kuruldu"],
    "founded":                ["kuruldu", "kuruluş"],
    "established":            ["kuruldu", "kuruluş"],
    "history":                ["tarihçe", "hakkında"],
    "research":               ["araştırma"],
}

_TR_SPECIFIC_CHARS = frozenset("ışğüöçİŞĞÜÖÇı")


def _build_retrieval_query(query: str) -> str:
    """Augment English queries with Turkish keyword equivalents for retrieval.

    English tokens don't score against Turkish content in keyword/reranker logic.
    Appending Turkish equivalents lets the existing Turkish scoring pipeline
    (keyword scoring, seed injection, intent detection) work for English input,
    without changing any of that logic.

    No-op when the query already contains Turkish-specific characters.
    """
    if any(c in _TR_SPECIFIC_CHARS for c in query):
        return query

    query_lower = query.lower()
    added: list[str] = []
    matched_positions: set[int] = set()

    for phrase in sorted(EN_TO_TR_QUERY_MAP, key=len, reverse=True):
        idx = query_lower.find(phrase)
        if idx == -1:
            continue
        span = set(range(idx, idx + len(phrase)))
        if span & matched_positions:
            continue  # already covered by a longer phrase match
        matched_positions |= span
        added.extend(EN_TO_TR_QUERY_MAP[phrase])

    if not added:
        return query

    seen: set[str] = set()
    unique: list[str] = []
    for term in added:
        if term not in seen:
            seen.add(term)
            unique.append(term)

    return query + " " + " ".join(unique)


NOISE_SOURCE_TERMS = [
    "duyuru",
    "announcement",
    "haber",
    "news",
    "kariyer",
    "career",
    "genel",
    "general",
    "etkinlik",
    "etkinlikler",
    "event",
    "rektorluk",
]

RETRIEVAL_NOISE_TERMS = ["duyuru", "haber", "etkinlik", "etkinlikler", "rektorluk"]

FACULTY_QUERY_TERMS = [
    "fakulte",
    "fakulteler",
    "hangi fakulteler",
    "lisans programi",
]

FACULTY_SIGNAL_TERMS = [
    "tip",
    "eczacilik",
    "saglik",
    "muhendislik",
    "toplum",
    "bilimleri",
]

FACULTY_LIST_PHRASES = [
    "lisans programi kapsaminda",
    "fakultelerimiz bulunuyor",
    "fakulteleri bulunmaktadir",
    "fakulteleri bulunuyor",
]

PROMO_NOISE_TERMS = [
    "daha fazla bilgi",
    "aday ogrenci",
    "kampus yasami",
    "kariyer firsatlari",
    "bilim ve teknolojiden beslenen egitim hayati",
]

CATALOG_QUERY_ACTION_TERMS = ["hangi", "neler", "listesi", "var"]
CATALOG_QUERY_DOMAIN_TERMS = [
    "fakulte",
    "bolum",
    "program",
    "lisans",
    "yuksek lisans",
    "doktora",
]

CATALOG_SIGNAL_TERMS = [
    "fakulte",
    "fakulteler",
    "bolum",
    "program",
    "lisans programi",
    "akademik",
    "muhendislik",
    "saglik",
    "eczacilik",
    "tip",
]

CATALOG_URL_POSITIVE_TERMS = ["/akademik/", "/lisans/", "/fakultesi", "/bolumler/", "/program"]
CATALOG_URL_NEGATIVE_TERMS = ["/haber", "/duyuru", "/news", "/etkinlik", "/kadro", "/ogretim-elemani"]

CATALOG_EXCLUDE_TERMS = [
    "ogretim elemani",
    "haklari",
    "sorumluluklari",
    "prof.",
    "doc.",
    "dr.",
    "tedavi",
    "kongre",
    "makale",
    "roportaj",
    "haber",
    "duyuru",
    "etkinlik",
    "rektorluk",
    "aday ogrenci",
    "kampus yasami",
    "kariyer",
]

CATALOG_STRONG_PHRASES = [
    "lisans programi kapsaminda",
    "fakultelerimiz bulunuyor",
    "fakulteleri bulunmaktadir",
]

CATALOG_EXPANSION_TERMS = [
    "fakulteler",
    "bolumler",
    "lisans programlari",
    "akademik",
    "fakultesi",
    "lisans",
]

EARLY_CATALOG_DOWNRANK_TERMS = [
    "sikca sorulan sorular",
    "e-bulten",
    "ebulten",
    "yonetim",
    "ogretim elemani",
    "kulup",
    "haber",
    "duyuru",
    "etkinlik",
    "roportaj",
    "makale",
]

LIST_PAGE_DETECT_PHRASES = [
    "fakultelerimiz",
    "lisans programi kapsaminda",
    "fakultelerimiz bulunuyor",
    "fakulteleri bulunmaktadir",
    "fakulteleri bulunuyor",
]

LIST_PAGE_FACULTY_TERMS = [
    "tip",
    "eczacilik",
    "saglik bilimleri",
    "insan ve toplum bilimleri",
    "muhendislik",
    "muhendislik ve doga bilimleri",
    "fen edebiyat",
    "hukuk",
    "isletme",
    "iletisim",
]

# Raw Turkish faculty names used for explicit-list detection (matched against un-normalized content).
EXPLICIT_FACULTY_LIST_TERMS = [
    "Tıp",
    "Eczacılık",
    "Sağlık Bilimleri",
    "İnsan ve Toplum Bilimleri",
    "Mühendislik",
    "Doğa Bilimleri",
    "Fen Edebiyat",
    "Hukuk",
    "İşletme",
    "İletişim",
]

SINGLE_FACULTY_TITLE_PATTERNS = [
    "tip fakultesi",
    "eczacilik fakultesi",
    "saglik bilimleri fakultesi",
    "muhendislik fakultesi",
    "insan ve toplum bilimleri fakultesi",
    "muhendislik ve doga bilimleri fakultesi",
]

HARD_NOISE_CONTENT_TERMS = [
    "kutuphane",
    "e-bulten",
    "ebulten",
    "etkinlik",
    "duyuru",
    "haber",
    "tez",
    "yayin",
    "kongre",
]

UNDERGRADUATE_URL_POSITIVE_TERMS = [
    "/akademik/lisans",
    "/lisans/",
    "/bolumler/",
    "/muhendisligi",
    "/program",
]

GRADUATE_EXCLUSION_TERMS = [
    "lisansustu",
    "enstitu",
    "yuksek lisans",
    "doktora",
    "anabilim dali",
    "sbe hakkinda",
    "saglik bilimleri enstitusu",
]

UNDERGRADUATE_CONTENT_BOOST_TERMS = [
    "lisans programlari",
    "lisans bolum",
    "bolumu",
    "muhendisligi",
]

INTENT_KEYWORD_GROUPS = {
    "faculty": {
        "triggers": ["fakulte", "fakulteler", "hangi fakulteler", "lisans programi"],
        "boost_terms": ["fakulte", "faculty", "muhendislik", "tip", "saglik"],
    },
    "contact": {
        "triggers": ["iletisim"],
        "boost_terms": ["iletisim", "contact"],
    },
    "department": {
        "triggers": ["bolum"],
        "boost_terms": ["bolum", "program"],
    },
}

IRRELEVANT_DOMAIN_TERMS = ["fitness", "spor", "gym", "cardio", "etkinlik"]

QUERY_STOPWORDS = {
    "ve",
    "veya",
    "ile",
    "icin",
    "için",
    "hakkinda",
    "hakkında",
    "bilgi",
    "ver",
    "nedir",
    "nasil",
    "nasıl",
    "olan",
    "olanlar",
    "bu",
    "su",
    "şu",
    "bir",
    "mi",
    "mu",
    "mü",
    "midir",
    "hangi",
    "var",
}

# ── Text Chunking ────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """
    Split text into overlapping chunks for embedding.

    Uses a smart splitting strategy:
    1. Try to split on paragraph boundaries
    2. Then on sentence boundaries
    3. Fall back to word boundaries
    """
    if not text or not text.strip():
        return []

    # Clean the text
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = text.strip()

    # Split into paragraphs first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        # If adding this paragraph exceeds chunk_size, finalize current chunk
        if current_chunk and len(current_chunk) + len(para) + 2 > chunk_size:
            chunks.append(current_chunk.strip())
            # Keep overlap from the end of current chunk
            words = current_chunk.split()
            overlap_words = words[-overlap:] if len(words) > overlap else words
            current_chunk = " ".join(overlap_words) + "\n\n" + para
        else:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # Handle case where a single paragraph is too long
    final_chunks = []
    for chunk in chunks:
        if len(chunk) > chunk_size * 2:
            # Split long chunks by sentences
            sentences = re.split(r"(?<=[.!?])\s+", chunk)
            sub_chunk = ""
            for sentence in sentences:
                if sub_chunk and len(sub_chunk) + len(sentence) + 1 > chunk_size:
                    final_chunks.append(sub_chunk.strip())
                    sub_chunk = sentence
                else:
                    sub_chunk = sub_chunk + " " + sentence if sub_chunk else sentence
            if sub_chunk.strip():
                final_chunks.append(sub_chunk.strip())
        else:
            final_chunks.append(chunk)

    return final_chunks


class RAGService:
    """
    Retrieval-Augmented Generation service.
    Handles the full pipeline: chunk → embed → store → retrieve → augment.
    """

    def __init__(self):
        self._ensure_pgvector()
        self._auto_bootstrap_attempted = False

    def _ensure_pgvector(self):
        """Ensure pgvector extension is installed in PostgreSQL."""
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        except Exception as e:
            logger.warning(f"Could not create pgvector extension: {e}")

    # ── Indexing Pipeline ────────────────────────────────

    def process_webpage(self, webpage: WebPage, force: bool = False) -> int:
        """
        Process a webpage: chunk text, generate embeddings, store in DB.

        Returns:
            Number of chunks created
        """
        if webpage.is_processed and not force:
            logger.info(f"Skipping already processed page: {webpage.url}")
            return 0

        if not webpage.content or not webpage.content.strip():
            logger.warning(f"Empty content for page: {webpage.url}")
            return 0

        # Delete existing chunks if reprocessing
        webpage.chunks.all().delete()

        # Chunk the text
        chunks = chunk_text(webpage.content)
        if not chunks:
            return 0

        logger.info(f"Processing {len(chunks)} chunks for: {webpage.title or webpage.url}")

        created_count = 0
        for i, chunk_text_content in enumerate(chunks):
            # Generate embedding
            embedding = llm_service.get_embedding(chunk_text_content)

            DocumentChunk.objects.create(
                web_page=webpage,
                chunk_index=i,
                content=chunk_text_content,
                embedding=embedding,
                token_count=len(chunk_text_content.split()),
                metadata={
                    "title": webpage.title,
                    "url": webpage.url,
                    "source": webpage.source,
                    "category": webpage.category,
                },
            )
            created_count += 1

        # Mark as processed
        webpage.is_processed = True
        webpage.save(update_fields=["is_processed"])

        logger.info(f"Created {created_count} chunks for: {webpage.title or webpage.url}")
        return created_count

    def process_all_unprocessed(self) -> int:
        """Process all unprocessed web pages."""
        pages = WebPage.objects.filter(is_processed=False)
        total = 0
        for page in pages:
            total += self.process_webpage(page)
        return total

    def _bootstrap_chunks_if_needed(self):
        """Auto-process pages when the chunk index is empty.

        This closes the common pipeline gap where pages are scraped into WebPage
        but embedding generation is never executed.
        """
        if self._auto_bootstrap_attempted:
            return

        self._auto_bootstrap_attempted = True

        if not getattr(settings, "RAG_AUTO_INDEX_ON_QUERY", True):
            return

        if DocumentChunk.objects.exists():
            return

        pending_qs = WebPage.objects.filter(is_processed=False).order_by("id")
        pending_count = pending_qs.count()
        if pending_count == 0:
            return

        max_pages = getattr(settings, "RAG_AUTO_INDEX_MAX_PAGES", 0)
        if max_pages and max_pages > 0:
            pending_qs = pending_qs[:max_pages]

        logger.warning(
            "DocumentChunk index is empty. Auto-processing %s pending pages before retrieval.",
            pending_qs.count(),
        )

        created_total = 0
        for page in pending_qs:
            created_total += self.process_webpage(page)

        logger.info("Auto-index bootstrap complete. Created %s chunks.", created_total)

    # ── Retrieval ────────────────────────────────────────

    def _serialize_chunk(self, chunk: DocumentChunk, score: float, match_type: str) -> dict:
        """Convert a chunk object into a unified search result dict."""
        return {
            "content": chunk.content,
            "url": chunk.metadata.get("url", chunk.web_page.url),
            "title": chunk.metadata.get("title", chunk.web_page.title),
            "source": chunk.metadata.get("source", chunk.web_page.source),
            "category": chunk.metadata.get("category", chunk.web_page.category),
            "score": round(max(0.0, min(score, 1.0)), 4),
            "match_type": match_type,
        }

    def _normalize_text(self, text: str) -> str:
        """Normalize Turkish characters and whitespace for matching."""
        normalized = (text or "").translate(TR_CHAR_TRANSLATION).lower()
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _query_tokens(self, query: str) -> list[str]:
        """Normalize query into tokens for keyword matching."""
        cleaned = re.sub(r"[^\w\s]", " ", self._normalize_text(query))
        return [token for token in cleaned.split() if len(token) > 1]

    def _raw_query_tokens(self, query: str) -> list[str]:
        """Extract raw lowercase tokens (without Turkish normalization)."""
        cleaned = re.sub(r"[^\w\s]", " ", (query or "").lower())
        return [token for token in cleaned.split() if len(token) > 1]

    def _expand_query_terms(self, query: str, tokens: list[str]) -> list[str]:
        """Expand user query with domain synonyms for better recall."""
        normalized_query = self._normalize_text(query)
        terms = [normalized_query]
        terms.extend(tokens)

        for phrase, expansions in QUERY_EXPANSIONS.items():
            if phrase in normalized_query:
                terms.extend(expansions)

        # Also trigger expansions if all phrase tokens are present.
        token_set = set(tokens)
        for phrase, expansions in QUERY_EXPANSIONS.items():
            phrase_tokens = set(phrase.split())
            if phrase_tokens and phrase_tokens.issubset(token_set):
                terms.extend(expansions)

        # Deduplicate while preserving order.
        return list(dict.fromkeys([t for t in terms if t]))

    def _process_relevant_pending_pages(self, query_terms: list[str]) -> int:
        """Process pending pages that are likely relevant to the current query."""
        if not getattr(settings, "RAG_AUTO_INDEX_RELEVANT_PENDING", True):
            return 0

        pending_qs = WebPage.objects.filter(is_processed=False)
        if not pending_qs.exists():
            return 0

        q_filter = Q()
        for term in query_terms[:20]:
            if len(term) < 2:
                continue
            q_filter |= Q(url__icontains=term)
            q_filter |= Q(title__icontains=term)
            q_filter |= Q(category__icontains=term)

        if not q_filter.children:
            return 0

        max_pages = max(1, int(getattr(settings, "RAG_AUTO_INDEX_RELEVANT_MAX_PAGES", 10)))
        candidates = (
            pending_qs
            .filter(q_filter)
            .order_by("-updated_at", "id")[:max_pages]
        )

        processed = 0
        for page in candidates:
            created = self.process_webpage(page)
            if created > 0:
                processed += 1

        if processed:
            logger.info(
                "Auto-indexed %s pending relevant pages for retrieval query.",
                processed,
            )
        return processed

    def _quality_filtered_queryset(self):
        """Exclude overly short / low-information chunks before ranking."""
        min_chars = max(1, int(getattr(settings, "RAG_MIN_CHUNK_CHARS", 120)))
        return (
            DocumentChunk.objects
            .exclude(content__isnull=True)
            .exclude(content__exact="")
            .select_related("web_page")
            .annotate(content_len=Length("content"))
            .filter(content_len__gte=min_chars)
        )

    def _chunk_blob(self, chunk: DocumentChunk) -> str:
        """Create normalized searchable text blob from chunk and page fields."""
        metadata = chunk.metadata or {}
        blob = " ".join([
            chunk.content or "",
            chunk.web_page.title or "",
            chunk.web_page.url or "",
            chunk.web_page.category or "",
            str(metadata.get("title", "")),
            str(metadata.get("url", "")),
            str(metadata.get("category", "")),
        ])
        return self._normalize_text(blob)

    def _contains_any_term(self, blob: str, terms: list[str]) -> bool:
        return any(term and term in blob for term in terms)

    def _detect_query_intents(self, query: str) -> list[str]:
        """Detect coarse query intent from normalized text using generic trigger groups."""
        normalized_query = self._normalize_text(query)
        intents = []

        for intent_name, config in INTENT_KEYWORD_GROUPS.items():
            triggers = config.get("triggers", [])
            if any(trigger in normalized_query for trigger in triggers):
                intents.append(intent_name)

        return intents

    def _is_faculty_list_query(self, query: str) -> bool:
        """Detect faculty-list intent queries."""
        normalized_query = self._normalize_text(query)
        return any(term in normalized_query for term in FACULTY_QUERY_TERMS)

    def _is_catalog_query(self, query: str) -> bool:
        """Detect list/catalog style academic queries in a general way."""
        normalized_query = self._normalize_text(query)
        has_action = any(term in normalized_query for term in CATALOG_QUERY_ACTION_TERMS)
        has_domain = any(term in normalized_query for term in CATALOG_QUERY_DOMAIN_TERMS)
        return has_action and has_domain

    def _is_faculty_query(self, query: str) -> bool:
        """Detect explicit faculty-listing intent ('hangi fakulteler var' etc.)."""
        norm = self._normalize_text(query)
        return any(t in norm for t in ["hangi fakulte", "fakulteler", "kac fakulte", "fakultelerimiz"])

    def _is_graduate_query(self, query: str) -> bool:
        """Detect graduate/postgraduate program intent."""
        norm = self._normalize_text(query)
        return any(t in norm for t in ["yuksek lisans", "lisansustu", "doktora", "saglik bilimleri enstitusu", " sbe"])

    def _is_undergraduate_program_query(self, query: str) -> bool:
        """Detect undergraduate program-listing intent ('lisans programlari neler' etc.)."""
        if self._is_graduate_query(query):
            return False
        norm = self._normalize_text(query)
        has_action = any(t in norm for t in CATALOG_QUERY_ACTION_TERMS)
        has_lisans = "lisans" in norm
        has_program = any(t in norm for t in ["program", "programlari"])
        return has_action and (has_lisans or has_program)

    def _is_department_query(self, query: str) -> bool:
        """Detect department-listing intent ('hangi bolumler var' etc.)."""
        norm = self._normalize_text(query)
        has_action = any(t in norm for t in CATALOG_QUERY_ACTION_TERMS)
        return has_action and any(t in norm for t in ["bolum", "bolumler"])

    def _has_academic_catalog_signal(self, title: str, content: str, url: str) -> bool:
        """Return True when result resembles an academic catalog/list page."""
        title_text = self._normalize_text(title)
        content_text = self._normalize_text(content)
        url_text = self._normalize_text(url)
        combined = f"{title_text} {content_text} {url_text}".strip()

        signal_hits = sum(1 for term in CATALOG_SIGNAL_TERMS if term in combined)
        has_list_like = (str(content or "").count(",") + str(content or "").count(";")) >= 2

        word_count = len([w for w in re.split(r"\s+", str(content_text or "")) if w])
        has_sentence = bool(re.search(r"[.!?]", str(content or "")))
        informative = (len(content_text) > 80) and (word_count >= 10) and has_sentence

        return informative and (signal_hits >= 2 or has_list_like)

    def _catalog_special_boost(self, title: str, content: str, url: str) -> float:
        """Compute strong catalog-query boosts from phrase/list/keyword/url signals."""
        combined_norm = self._normalize_text(f"{title} {content}")
        raw_content = str(content or "")
        raw_url = str(url or "").lower()

        boost = 0.0

        phrase_hits = sum(1 for phrase in CATALOG_STRONG_PHRASES if phrase in combined_norm)
        boost += min(1.2, phrase_hits * 0.55)

        keyword_hits = self._faculty_keyword_hits(combined_norm)
        if keyword_hits >= 2:
            boost += 0.75

        list_like_hits = raw_content.count(",") + raw_content.count(";")
        if list_like_hits >= 2:
            boost += 0.55

        positive_url_hits = sum(1 for term in CATALOG_URL_POSITIVE_TERMS if term in raw_url)
        boost += min(0.8, positive_url_hits * 0.25)

        return boost

    def _is_catalog_excluded_result(self, title: str, content: str, url: str) -> bool:
        """Hard exclude non-catalog/staff/news/promo style results for catalog queries."""
        blob = self._normalize_text(f"{title} {content} {url}")
        return any(term in blob for term in CATALOG_EXCLUDE_TERMS)

    def _catalog_query_variants(self, query: str) -> list[str]:
        """Build broader catalog-oriented query variants for candidate generation."""
        base = (query or "").strip()
        if not base:
            return []

        variants = [base]
        normalized_base = self._normalize_text(base)

        for term in CATALOG_EXPANSION_TERMS:
            if term in normalized_base:
                continue
            variants.append(f"{base} {term}")

        return list(dict.fromkeys([v for v in variants if v]))

    def _dedupe_serialized_results(self, results: list[dict]) -> list[dict]:
        """Dedupe serialized result dicts by url/title/content snippet."""
        deduped: list[dict] = []
        seen_keys: set[tuple[str, str, str]] = set()

        for item in results:
            key = (
                str(item.get("url", "") or ""),
                str(item.get("title", "") or ""),
                str(item.get("content", "") or "")[:180],
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(item)

        return deduped

    def _catalog_rerank_candidates(self, candidates: list[dict], limit: int, query: str = "") -> list[dict]:
        """Catalog-specific reranker: explicit_list > list_page > catalog signal > keyword > semantic."""
        undergrad_query = self._is_undergraduate_program_query(query) if query else False
        dept_query = self._is_department_query(query) if query else False
        grad_intent = self._is_graduate_query(query) if query else False
        non_grad_catalog = (undergrad_query or dept_query) and not grad_intent

        scored: list[tuple[float, float, float, float, float, float, dict]] = []

        for item in candidates:
            title = str(item.get("title", "") or "")
            content = str(item.get("content", "") or "")
            url = str(item.get("url", "") or "")
            blob = self._normalize_text(f"{title} {content} {url}")

            if self._is_catalog_excluded_result(title, content, url):
                continue

            semantic_score = float(item.get("score", 0.0) or 0.0)
            keyword_score = float(item.get("_keyword_score", 0.0) or 0.0)
            source_priority = 1.0 if str(item.get("match_type", "") or "").startswith("keyword") else 0.0
            catalog_signal = 0.0

            # Tier 1: explicit faculty-list chunk.
            is_explicit = self._is_explicit_faculty_list_chunk(content)
            explicit_boost = 8.0 if is_explicit else 0.0

            # Tier 2: list page.
            is_list = is_explicit or self._is_list_page(title, content)
            if is_list:
                list_page_boost = 5.0
            elif self._is_single_faculty_page(title, content):
                list_page_boost = -2.0
            else:
                list_page_boost = 0.0

            if self._has_academic_catalog_signal(title, content, url):
                catalog_signal += 1.2

            catalog_signal += self._catalog_special_boost(title, content, url)

            downrank_hits = sum(1 for term in EARLY_CATALOG_DOWNRANK_TERMS if term in blob)
            if downrank_hits:
                catalog_signal -= min(1.4, downrank_hits * 0.45)

            if non_grad_catalog:
                raw_url_lower = url.lower()
                ug_url_hits = sum(1 for t in UNDERGRADUATE_URL_POSITIVE_TERMS if t in raw_url_lower)
                catalog_signal += min(3.0, ug_url_hits * 1.5)
                ug_content_hits = sum(1 for t in UNDERGRADUATE_CONTENT_BOOST_TERMS if t in blob)
                catalog_signal += min(2.0, ug_content_hits * 0.8)
                grad_hits = sum(1 for t in GRADUATE_EXCLUSION_TERMS if t in blob)
                catalog_signal -= min(6.0, grad_hits * 3.0)

            scored.append((explicit_boost, list_page_boost, catalog_signal, source_priority, keyword_score, semantic_score, item))

        # Sort: explicit_list > list_page > catalog_signal > source_priority > keyword_score > semantic.
        scored.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4], x[5]), reverse=True)

        selected: list[dict] = []
        seen_urls: set[str] = set()
        for _, _, _, _, _, _, item in scored:
            url = str(item.get("url", "") or "").strip()
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            selected.append(item)
            if len(selected) >= max(3, int(limit) if limit else 5):
                break

        return selected

    def _faculty_keyword_hits(self, text: str) -> int:
        """Count faculty-signal keyword hits in normalized text."""
        normalized_text = self._normalize_text(text)
        return sum(1 for term in FACULTY_SIGNAL_TERMS if term in normalized_text)

    def _has_list_structure(self, text: str) -> bool:
        """Detect list-like punctuation pattern from raw text."""
        raw = str(text or "")
        separators = raw.count(",") + raw.count(";")
        if separators >= 2:
            return True
        return bool(re.search(r":[^.]*[,;]", raw))

    def _has_faculty_list_phrase(self, text: str) -> bool:
        """Detect faculty-list phrasing in normalized text."""
        normalized_text = self._normalize_text(text)
        return any(phrase in normalized_text for phrase in FACULTY_LIST_PHRASES)

    def _is_list_page(self, title: str, content: str) -> bool:
        """Detect pages that enumerate multiple faculties/programs (list pages).

        A list page is identified by:
        - Explicit list phrases ("fakultelerimiz", "lisans programi kapsaminda", etc.)
        - 3+ distinct faculty-like terms appearing together
        - Comma-separated academic content with 2+ faculty signals
        """
        combined = self._normalize_text(f"{title} {content}")

        if any(phrase in combined for phrase in LIST_PAGE_DETECT_PHRASES):
            return True

        faculty_hits = sum(1 for term in LIST_PAGE_FACULTY_TERMS if term in combined)
        if faculty_hits >= 3:
            return True

        raw = str(content or "")
        if raw.count(",") >= 3 and faculty_hits >= 2:
            return True

        return False

    def _is_explicit_faculty_list_chunk(self, content: str) -> bool:
        """Return True when a chunk explicitly enumerates multiple ACU faculties.

        Uses strict checks to avoid false positives from pages that merely
        *mention* faculty names in passing (e.g. English-prep or fee pages).

        True positives: dense comma-separated faculty list within ≤300 chars,
        or canonical pair "Tıp, Eczacılık", or list phrase + 2 term hits.
        """
        raw = str(content or "")

        # Strongest anchor: canonical comma-separated pair unique to faculty overview.
        if "Tıp, Eczacılık" in raw or "Eczacılık, Tıp" in raw:
            return True

        # Collect first-occurrence positions with their term name.
        hit_positions: list[tuple[int, str]] = []
        for term in EXPLICIT_FACULTY_LIST_TERMS:
            idx = raw.find(term)
            if idx >= 0:
                hit_positions.append((idx, term))
        hit_positions.sort()

        if len(hit_positions) >= 3:
            # Require the 3-term window to START with "Tıp" (canonical first faculty).
            # This rejects false positives where faculty names appear scattered and
            # "Tıp" comes after other terms (e.g. English-prep listing).
            for i in range(len(hit_positions) - 2):
                pos_start, term_start = hit_positions[i]
                pos_end = hit_positions[i + 2][0]
                if pos_end - pos_start <= 200 and term_start == "Tıp":
                    return True

        # List-detection phrase + at least 2 term hits (phrase anchors context).
        norm = self._normalize_text(raw)
        if any(phrase in norm for phrase in LIST_PAGE_DETECT_PHRASES):
            if len(hit_positions) >= 2:
                return True

        return False

    def _is_single_faculty_page(self, title: str, content: str) -> bool:
        """Return True when title/content points to exactly one faculty (not a list)."""
        if self._is_explicit_faculty_list_chunk(content):
            return False
        if self._is_list_page(title, content):
            return False
        norm_title = self._normalize_text(title)
        return any(pattern in norm_title for pattern in SINGLE_FACULTY_TITLE_PATTERNS) or (
            "fakultesi" in self._normalize_text(content)
            and not self._is_list_page(title, content)
        )

    def _has_promo_noise(self, text: str) -> bool:
        """Detect promotional/student-marketing copy."""
        normalized_text = self._normalize_text(text)
        return any(term in normalized_text for term in PROMO_NOISE_TERMS)

    def _faculty_list_signal(self, title: str, content: str) -> tuple[bool, int, bool, bool]:
        """Return faculty-list signal tuple: (has_signal, keyword_hits, list_like, phrase_hit)."""
        combined = f"{title} {content}".strip()
        keyword_hits = self._faculty_keyword_hits(combined)
        list_like = self._has_list_structure(content) or self._has_list_structure(title)
        phrase_hit = self._has_faculty_list_phrase(combined)
        has_signal = (keyword_hits >= 2) or (list_like and keyword_hits >= 1) or phrase_hit
        return has_signal, keyword_hits, list_like, phrase_hit

    def _intent_hits_by_field(self, title: str, url: str, content: str, intent_name: str) -> tuple[int, int, int]:
        """Return per-field intent-term hit counts for a detected intent."""
        config = INTENT_KEYWORD_GROUPS.get(intent_name, {})
        terms = config.get("boost_terms", [])

        title_hits = sum(1 for term in terms if term in title)
        url_hits = sum(1 for term in terms if term in url)
        content_hits = sum(1 for term in terms if term in content)
        return title_hits, url_hits, content_hits

    def _query_keywords(self, query: str) -> list[str]:
        """Extract simple lowercase keywords from query text."""
        lowered = (query or "").lower()
        tokens = re.split(r"\s+", lowered.strip())
        keywords = []
        for token in tokens:
            token = re.sub(r"[^\w\-çğıöşüÇĞİÖŞÜ]", "", token)
            if len(token) < 2:
                continue
            if token in QUERY_STOPWORDS:
                continue
            keywords.append(token)

            # Lightweight plural normalization for Turkish-like forms (e.g., fakulteler -> fakulte).
            if token.endswith(("lar", "ler")) and len(token) > 4:
                singular = token[:-3]
                if singular and singular not in QUERY_STOPWORDS:
                    keywords.append(singular)

        return list(dict.fromkeys(keywords))

    def _has_partial_keyword_match(self, text: str, keywords: list[str]) -> bool:
        """Flexible keyword match (substring/prefix) to avoid over-strict filtering."""
        if not text or not keywords:
            return False

        haystack = self._normalize_text(text)
        words = [w for w in haystack.split() if w]

        for keyword in keywords:
            key = self._normalize_text(keyword)
            if not key:
                continue
            if key in haystack:
                return True

            if len(key) >= 4:
                key_prefix = key[:4]
                if any(word.startswith(key_prefix) or key.startswith(word[:4]) for word in words if len(word) >= 4):
                    return True

            if any(key in word or word in key for word in words if len(word) >= 3):
                return True

        return False

    def _apply_result_filters(self, query: str, results: list[dict], limit: int = 5) -> list[dict]:
        """Score-only reranking: title/url boosts + noise penalty, then top 3-5."""
        if not results:
            return []

        keywords = self._query_keywords(query)
        normalized_keywords = [self._normalize_text(k) for k in keywords if self._normalize_text(k)]
        keyword_count = max(1, len(normalized_keywords))
        head_keyword = normalized_keywords[0] if normalized_keywords else ""
        query_intents = self._detect_query_intents(query)
        faculty_query = self._is_faculty_list_query(query) or ("faculty" in query_intents)
        catalog_query = self._is_catalog_query(query)
        undergrad_query = self._is_undergraduate_program_query(query)
        dept_query = self._is_department_query(query)
        grad_intent = self._is_graduate_query(query)
        non_grad_catalog = catalog_query and (undergrad_query or dept_query) and not grad_intent

        reranked: list[tuple[float, float, dict]] = []
        for result in results:
            try:
                base_score = float(result.get("score", 0.0) or 0.0)
            except (TypeError, ValueError):
                base_score = 0.0

            title = self._normalize_text(str(result.get("title", "") or ""))
            url = self._normalize_text(str(result.get("url", "") or ""))
            content = self._normalize_text(str(result.get("content", "") or ""))
            relevance_blob = f"{title} {url} {content}".strip()

            title_hits = sum(1 for keyword in normalized_keywords if keyword in title)
            url_hits = sum(1 for keyword in normalized_keywords if keyword in url)
            content_hits = sum(1 for keyword in normalized_keywords if keyword in content)

            matched_terms = {
                keyword
                for keyword in normalized_keywords
                if keyword in title or keyword in url or keyword in content
            }
            coverage = len(matched_terms) / keyword_count

            head_boost = 0.0
            if head_keyword:
                if head_keyword in title:
                    head_boost += 0.24
                if head_keyword in url:
                    head_boost += 0.28
                if head_keyword in content:
                    head_boost += 0.10

            # Significant boost for title keyword alignment.
            title_boost = 0.0
            if title_hits > 0:
                title_boost = 0.22 + (0.48 * (title_hits / keyword_count))

            # URL signal boost for query keyword alignment.
            url_boost = 0.0
            if url_hits > 0:
                url_boost = 0.10 + (0.28 * (url_hits / keyword_count))

            # Light extra URL boost for structural academic terms when query also carries them.
            structural_terms = ["muhendisligi", "muhendislik", "bolum", "fakulte"]
            structural_hits = sum(1 for term in structural_terms if term in normalized_keywords and term in url)
            structural_boost = min(0.08, structural_hits * 0.04)

            # Prefer results that cover multiple query keywords across fields.
            coverage_boost = 0.45 * coverage

            # Penalize low/zero query-term alignment to demote irrelevant semantic neighbors.
            relevance_penalty = 0.0
            if normalized_keywords and not matched_terms:
                relevance_penalty = 0.45
            elif normalized_keywords and len(matched_terms) == 1:
                relevance_penalty = 0.14

            # Extra penalty when title/url both have no keyword signal.
            if normalized_keywords and title_hits == 0 and url_hits == 0:
                relevance_penalty += 0.12

            if head_keyword and head_keyword not in matched_terms:
                relevance_penalty += 0.18

            # Penalize generic page titles unless query coverage is strong.
            generic_title_patterns = ["hakkinda", "program hakkinda", "about", "about program"]
            if any(pattern == title or title.startswith(pattern) for pattern in generic_title_patterns):
                if coverage < 0.67:
                    relevance_penalty += 0.18

            # Intent-aware boost from query type (faculty/contact/department) without filtering.
            intent_boost = 0.0
            for intent_name in query_intents:
                title_intent_hits, url_intent_hits, content_intent_hits = self._intent_hits_by_field(
                    title, url, content, intent_name
                )
                if title_intent_hits or url_intent_hits or content_intent_hits:
                    config = INTENT_KEYWORD_GROUPS.get(intent_name, {})
                    term_count = max(1, len(config.get("boost_terms", [])))
                    total_hits = title_intent_hits + url_intent_hits + content_intent_hits

                    # Favor title/url matches while still rewarding content alignment.
                    field_weighted_hits = (
                        (2.2 * title_intent_hits)
                        + (2.0 * url_intent_hits)
                        + (1.0 * content_intent_hits)
                    )
                    intent_boost += min(0.42, 0.10 + (field_weighted_hits / (term_count * 5.0)))

                    # Mild extra reward for richer intent-term coverage.
                    intent_boost += min(0.12, (total_hits / term_count) * 0.08)

                # Faculty intent should prefer explicit faculty signals in title/url.
                if intent_name == "faculty" and title_intent_hits == 0 and url_intent_hits == 0:
                    relevance_penalty += 0.24

            # Penalize clearly irrelevant domains for broad informational queries.
            irrelevant_hits = sum(1 for term in IRRELEVANT_DOMAIN_TERMS if term in relevance_blob)
            irrelevant_penalty = min(0.65, irrelevant_hits * 0.22)

            # For faculty-intent questions, de-prioritize news/announcement pages.
            if "faculty" in query_intents and ("/haberler/" in url or "/duyurular/" in url):
                irrelevant_penalty += 0.3

            # Downrank noisy sources/content but keep them in the pool.
            noise_blob = f"{title} {content}".strip()
            noise_hits = sum(1 for term in RETRIEVAL_NOISE_TERMS if term in noise_blob)
            noise_penalty = min(0.9, noise_hits * 0.28)
            if "/haberler/" in url or "/duyurular/" in url:
                noise_penalty += 0.15

            faculty_boost = 0.0
            promo_penalty = 0.0
            catalog_boost = 0.0
            catalog_penalty = 0.0
            list_page_score = 0.0
            explicit_list_score = 0.0
            has_faculty_signal, faculty_keyword_hits, list_like, phrase_hit = self._faculty_list_signal(title, content)

            raw_title = str(result.get("title", "") or "")
            raw_content = str(result.get("content", "") or "")

            # Tier 1: explicit faculty-list chunk (+8) — highest priority.
            is_explicit_list = self._is_explicit_faculty_list_chunk(raw_content)
            if is_explicit_list:
                explicit_list_score += 8.0

            # Tier 2: list page (+5) — general overview page with multiple faculties.
            is_list = is_explicit_list or self._is_list_page(raw_title, raw_content)
            if is_list:
                list_page_score += 5.0
            elif self._is_single_faculty_page(raw_title, raw_content):
                # Single faculty page — downrank hard relative to list/explicit chunks.
                list_page_score -= 2.0

            if self._has_promo_noise(f"{title} {content}"):
                promo_penalty += 1.10 if faculty_query else 0.45

            if faculty_query:
                if has_faculty_signal:
                    faculty_boost += 0.55
                    if faculty_keyword_hits >= 2:
                        faculty_boost += 0.55
                    if list_like:
                        faculty_boost += 0.40
                    if phrase_hit:
                        faculty_boost += 0.55
                else:
                    relevance_penalty += 0.95

            if catalog_query:
                if self._is_catalog_excluded_result(title, content, url):
                    catalog_penalty += 1.50

                if self._has_academic_catalog_signal(title, content, url):
                    catalog_boost += 1.05
                else:
                    catalog_penalty += 1.05

                raw_url = str(result.get("url", "") or "").lower()
                positive_url_hits = sum(1 for term in CATALOG_URL_POSITIVE_TERMS if term in raw_url)
                negative_url_hits = sum(1 for term in CATALOG_URL_NEGATIVE_TERMS if term in raw_url)
                catalog_boost += min(0.8, positive_url_hits * 0.25)
                catalog_penalty += min(1.0, negative_url_hits * 0.35)
                catalog_boost += self._catalog_special_boost(title, content, raw_url)

                if non_grad_catalog:
                    ug_url_hits = sum(1 for t in UNDERGRADUATE_URL_POSITIVE_TERMS if t in raw_url)
                    catalog_boost += min(2.0, ug_url_hits * 0.8)
                    ug_content_hits = sum(1 for t in UNDERGRADUATE_CONTENT_BOOST_TERMS if t in content)
                    catalog_boost += min(1.5, ug_content_hits * 0.6)
                    grad_hits = sum(1 for t in GRADUATE_EXCLUSION_TERMS if t in relevance_blob)
                    catalog_penalty += min(4.0, grad_hits * 2.0)

            keyword_score = float(result.get("_keyword_score", 0.0) or 0.0)

            adjusted_score = max(
                0.0,
                min(
                    16.0,
                    base_score
                    + explicit_list_score
                    + list_page_score
                    + title_boost
                    + url_boost
                    + structural_boost
                    + coverage_boost
                    + head_boost
                    + intent_boost
                    + faculty_boost
                    + catalog_boost
                    - relevance_penalty
                    - irrelevant_penalty
                    - noise_penalty
                    - promo_penalty
                    - catalog_penalty,
                ),
            )
            # Sort key: explicit_list_score > list_page_score > keyword_score > adjusted_score > semantic.
            reranked.append((explicit_list_score, list_page_score, keyword_score, adjusted_score, base_score, result))

        # Priority order: explicit faculty-list chunk > list page > keyword score > semantic score.
        reranked.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]), reverse=True)

        # Debug: explicit faculty-list candidates.
        explicit_list_items = [item for item in reranked if item[0] > 0]
        if explicit_list_items:
            logger.debug("RAG explicit faculty-list candidates: %s",
                         [(str(i[5].get("title",""))[:40], str(i[5].get("content",""))[:60]) for i in explicit_list_items[:5]])

        # Debug: list page candidates (non-explicit).
        list_page_items = [item for item in reranked if item[0] == 0 and item[1] > 0]
        if list_page_items:
            list_page_titles = [str(item[5].get("title", "") or "") for item in list_page_items[:5]]
            logger.debug("RAG list page candidates: %s", list_page_titles)

        bounded_limit = max(3, int(limit) if limit else 5)
        if len(reranked) < bounded_limit:
            bounded_limit = len(reranked)

        final_results: list[dict] = []
        seen_urls = set()
        for _els, _lps, _kws, adjusted_score, _, item in reranked:
            ranked_item = dict(item)
            ranked_item["score"] = round(adjusted_score, 4)
            url = str(ranked_item.get("url", "") or "").strip()
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            final_results.append(ranked_item)
            if len(final_results) >= bounded_limit:
                break

        return final_results

    def _catalog_second_pass_rerank(self, results: list[dict], max_items: int = 3) -> list[dict]:
        """Fallback rerank for catalog queries using broad candidate pool and strict exclusions."""
        scored: list[tuple[float, dict]] = []

        for result in results:
            title = str(result.get("title", "") or "")
            content = str(result.get("content", "") or "")
            url = str(result.get("url", "") or "")

            if self._is_catalog_excluded_result(title, content, url):
                continue
            if not self._has_academic_catalog_signal(title, content, url):
                continue

            score = float(result.get("score", 0.0) or 0.0)
            score += self._catalog_special_boost(title, content, url)
            scored.append((score, result))

        scored.sort(key=lambda item: item[0], reverse=True)

        selected: list[dict] = []
        seen_urls: set[str] = set()
        for _, item in scored:
            url = str(item.get("url", "") or "").strip()
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            selected.append(item)
            if len(selected) >= max(2, max_items):
                break

        return selected

    def _passes_hard_filter(self, chunk: DocumentChunk, query_terms: list[str]) -> bool:
        """Apply strict relevance constraints to remove unrelated chunks."""
        blob = self._chunk_blob(chunk)

        # Mandatory: at least one query term must exist in chunk/page fields.
        if not self._contains_any_term(blob, query_terms):
            return False

        return True

    def _field_hits(self, chunk: DocumentChunk, terms: list[str]) -> tuple[int, int, int, int]:
        """Return hit counts in (url, title, metadata, content)."""
        metadata = chunk.metadata or {}
        url_text = self._normalize_text(chunk.web_page.url or "")
        title_text = self._normalize_text(chunk.web_page.title or "")
        metadata_text = self._normalize_text(
            " ".join([
                str(metadata.get("url", "")),
                str(metadata.get("title", "")),
                str(metadata.get("category", "")),
                str(metadata.get("source", "")),
                chunk.web_page.category or "",
            ])
        )
        content_text = self._normalize_text(chunk.content or "")

        url_hits = sum(1 for term in terms if term in url_text)
        title_hits = sum(1 for term in terms if term in title_text)
        metadata_hits = sum(1 for term in terms if term in metadata_text)
        content_hits = sum(1 for term in terms if term in content_text)
        return url_hits, title_hits, metadata_hits, content_hits

    def _weighted_lexical_score(self, chunk: DocumentChunk, terms: list[str]) -> float:
        """Compute field-aware lexical score with explicit boosts.

        Boost order: URL > title > metadata > content
        """
        if not terms:
            return 0.0

        url_hits, title_hits, metadata_hits, content_hits = self._field_hits(chunk, terms)

        total_terms = max(1, len(terms))
        weighted_hits = (
            (3.0 * url_hits)
            + (4.0 * title_hits)
            + (1.5 * metadata_hits)
            + (1.0 * content_hits)
        )
        max_weighted = total_terms * 9.5
        base_score = max(0.0, min(weighted_hits / max_weighted, 1.0))

        # Title match must dominate ranking.
        if title_hits > 0:
            base_score += 0.2

        # URL matches are preferred; no URL match gets slight penalty.
        if url_hits > 0:
            base_score += 0.12
        else:
            base_score *= 0.75

        return max(0.0, min(base_score, 1.0))

    def _result_blob(self, result: dict) -> str:
        """Build a normalized searchable blob from serialized result fields."""
        return self._normalize_text(
            " ".join([
                str(result.get("title", "") or ""),
                str(result.get("url", "") or ""),
                str(result.get("category", "") or ""),
                str(result.get("source", "") or ""),
                str(result.get("content", "") or ""),
            ])
        )

    def _result_source_blob(self, result: dict) -> str:
        """Normalized blob for source-level filtering (without chunk body noise)."""
        return self._normalize_text(
            " ".join([
                str(result.get("title", "") or ""),
                str(result.get("url", "") or ""),
                str(result.get("category", "") or ""),
                str(result.get("source", "") or ""),
            ])
        )

    def _is_noise_source(self, result: dict) -> bool:
        """Exclude broadly generic pages (announcements/career/general etc)."""
        blob = self._result_source_blob(result)
        return any(term in blob for term in NOISE_SOURCE_TERMS)

    def _result_passes_query_filter(self, result: dict, query_terms: list[str]) -> bool:
        """Strict result-level relevance filter used before prompt context build."""
        blob = self._result_blob(result)

        if not self._contains_any_term(blob, query_terms):
            return False

        # Generic noise filter for context stage as well.
        if any(term in blob for term in RETRIEVAL_NOISE_TERMS):
            return False

        return True

    def _clean_results_for_context(self, query: str, results: list[dict]) -> list[dict]:
        """Context-stage ranking only: keep top relevant sources without hard filtering."""
        if not results:
            return []

        blocked_terms = ["hakkında", "iletişim", "tanıtım", "katalog", "menü", "hakkinda", "iletisim", "tanitim", "menu"]

        def has_real_sentence(content: str) -> bool:
            text = re.sub(r"\s+", " ", str(content or "")).strip()
            if len(text) < 50:
                return False
            if not re.search(r"[.!?]", text):
                return False
            words = [w for w in re.split(r"\s+", text) if w]
            return len(words) >= 8

        faculty_query = self._is_faculty_list_query(query)
        catalog_query = self._is_catalog_query(query)
        undergrad_query = self._is_undergraduate_program_query(query)
        dept_query = self._is_department_query(query)
        grad_intent = self._is_graduate_query(query)
        non_grad_catalog = catalog_query and (undergrad_query or dept_query) and not grad_intent
        norm_q_clean = self._normalize_text(query)
        founding_query = "ne zaman" in norm_q_clean or "kuruldu" in norm_q_clean

        if catalog_query:
            if faculty_query:
                intent_label = "faculty"
            elif undergrad_query:
                intent_label = "undergraduate_program"
            elif dept_query:
                intent_label = "department"
            elif grad_intent:
                intent_label = "graduate"
            else:
                intent_label = "general_catalog"
            logger.info("RAG query intent: %s (query=%s)", intent_label, query[:120])

        top_sources = min(5, max(3, int(getattr(settings, "RAG_CONTEXT_TOP_SOURCES", 3))))
        reranked = self._apply_result_filters(query, results, limit=max(top_sources, 5))

        if catalog_query:
            preview_titles = [str(item.get("title", "") or "") for item in reranked[:10]]
            logger.info("RAG catalog top candidate titles (pre-clean): %s", preview_titles)

        cleaned: list[dict] = []
        seen_urls = set()
        for result in reranked:
            content = str(result.get("content", "") or "")
            title = str(result.get("title", "") or "")
            url = str(result.get("url", "") or "").strip()
            blob = self._normalize_text(f"{title} {content}")

            if non_grad_catalog:
                grad_hits = sum(1 for t in GRADUATE_EXCLUSION_TERMS if t in blob)
                if grad_hits:
                    continue

            # For founding-year queries: skip non-informative chunks, prioritize hakkinda/universite pages.
            if founding_query:
                content_norm = self._normalize_text(content)
                has_year_and_founding = bool(
                    re.search(r'\d{4}', content) and
                    any(t in content_norm for t in ["kurul", "yilin", "yilinda", "tarih"])
                )
                has_about_url = any(t in self._normalize_text(url) for t in ["hakkinda/universite", "hakkimizda"])
                if not has_year_and_founding and not has_about_url:
                    continue

            # Explicit faculty-list early-exit: only activate for faculty-list queries.
            # For other queries (nedir, kuruldu, kampus, bolumleri) it fills slots with
            # wrong chunks and blocks the relevant content from entering context.
            if faculty_query and self._is_explicit_faculty_list_chunk(content):
                if url and url in seen_urls:
                    continue
                cleaned.append(result)
                if url:
                    seen_urls.add(url)
                if len(cleaned) >= top_sources:
                    break
                continue

            if any(term in blob for term in blocked_terms):
                continue

            if len(content.strip()) < 50:
                continue

            if not has_real_sentence(content):
                continue

            if self._has_promo_noise(f"{title} {content}"):
                continue

            if faculty_query and not catalog_query:
                has_signal, _, _, _ = self._faculty_list_signal(title, content)
                if not has_signal:
                    continue

            if catalog_query:
                if self._is_catalog_excluded_result(title, content, url):
                    continue
                if len(content.strip()) <= 80:
                    continue

                words = [w for w in re.split(r"\s+", content.strip()) if w]
                if len(words) < 10:
                    continue

                if not re.search(r"[.!?]", content):
                    continue

                if not self._has_academic_catalog_signal(title, content, url):
                    continue

            if url and url in seen_urls:
                continue
            cleaned.append(result)
            if url:
                seen_urls.add(url)
            if len(cleaned) >= top_sources:
                break

        if cleaned:
            logger.info(
                "RAG context ranking: raw=%s cleaned=%s top_sources=%s",
                len(results),
                len(cleaned),
                top_sources,
            )

            if faculty_query:
                debug_chunks = [
                    f"{str(item.get('title', '') or '')} | {str(item.get('content', '') or '').strip()[:120]}"
                    for item in cleaned
                ]
                logger.info("RAG faculty context selected chunks (%s): %s", len(cleaned), debug_chunks)

            if catalog_query:
                debug_titles = [str(item.get("title", "") or "") for item in cleaned]
                debug_urls = [str(item.get("url", "") or "") for item in cleaned]
                debug_content = [str(item.get("content", "") or "").strip()[:120] for item in cleaned]
                logger.info("RAG catalog selected titles [intent=%s]: %s", intent_label if catalog_query else "n/a", debug_titles)
                logger.info("RAG catalog selected urls: %s", debug_urls)
                logger.info("RAG catalog selected content preview: %s", debug_content)

            return cleaned

        if faculty_query:
            logger.warning("RAG faculty context selection returned 0 cleaned chunks for query: %s", query[:80])
            return []

        if catalog_query:
            fallback_candidates = self._catalog_second_pass_rerank(reranked, max_items=min(3, top_sources))
            fallback_titles = [str(item.get("title", "") or "") for item in fallback_candidates]
            logger.warning(
                "RAG catalog context selection returned 0 cleaned chunks for query: %s; fallback candidates=%s",
                query[:80],
                fallback_titles,
            )
            return fallback_candidates

        return reranked[:top_sources]

    def _fallback_search(self, top_k: int) -> list[dict]:
        """Return the most content-rich chunks when normal retrieval yields nothing."""
        fallback_k = max(top_k, getattr(settings, "RAG_FALLBACK_TOP_K", 8))
        fallback_qs = (
            self._quality_filtered_queryset()
            .order_by("-token_count", "-content_len", "id")[:fallback_k]
        )

        fallback_results = [
            self._serialize_chunk(chunk, score=0.1, match_type="fallback")
            for chunk in fallback_qs
        ]
        logger.info("Retrieval[fallback] returned %s chunks", len(fallback_results))
        return fallback_results

    def search(self, query: str, top_k: Optional[int] = None) -> list[dict]:
        """
        Perform semantic search using pgvector cosine similarity.

        Returns:
            List of dicts with keys: content, url, title, source, score
        """
        if top_k is None:
            top_k = settings.RAG_TOP_K

        self._bootstrap_chunks_if_needed()
        query = _build_retrieval_query(query)

        catalog_query = self._is_catalog_query(query)

        raw_terms = self._raw_query_tokens(query)
        normalized_tokens = self._query_tokens(query)
        expanded_terms = self._expand_query_terms(query, normalized_tokens)
        if catalog_query:
            expanded_terms = list(dict.fromkeys([*expanded_terms, *CATALOG_EXPANSION_TERMS]))
        query_terms = list(dict.fromkeys([query.strip().lower(), *raw_terms, *expanded_terms]))
        self._process_relevant_pending_pages(query_terms)

        # Generate query embedding (cached per unique query text)
        query_embedding = _get_cached_embedding(query)
        if query_embedding is None:
            logger.warning("Could not generate query embedding, falling back to keyword search")
            keyword_results = self._keyword_search(query, top_k)
            keyword_results = self._apply_result_filters(query, keyword_results, limit=5)
            logger.info("Retrieval[keyword-only] returned %s chunks", len(keyword_results))
            return keyword_results

        # Semantic search with pgvector
        try:
            candidates = (
                DocumentChunk.objects
                .filter(embedding__isnull=False)
                .select_related("web_page")
                .annotate(distance=CosineDistance("embedding", query_embedding))
                .order_by("distance")[: max(top_k * 3, top_k)]
            )

            threshold = settings.RAG_SIMILARITY_THRESHOLD
            scored = []
            for chunk in candidates:
                score = 1 - float(chunk.distance)  # Convert distance to similarity
                scored.append((chunk, score))

            strong_semantic = [
                self._serialize_chunk(chunk, score=score, match_type="semantic")
                for chunk, score in scored
                if score >= threshold
            ]
            relaxed_semantic = [
                self._serialize_chunk(chunk, score=score, match_type="semantic-relaxed")
                for chunk, score in scored[: max(top_k * 2, top_k)]
            ]

            if catalog_query:
                keyword_pool: list[dict] = []
                for variant in self._catalog_query_variants(query):
                    keyword_pool.extend(self._keyword_search(variant, max(top_k * 20, 200)))
                keyword_candidates = self._dedupe_serialized_results(keyword_pool)
            else:
                keyword_candidates = self._keyword_search(query, max(top_k * 20, 200))

            if catalog_query:
                semantic_titles = [str(item.get("title", "") or "") for item in relaxed_semantic[:10]]
                keyword_titles = [str(item.get("title", "") or "") for item in keyword_candidates[:10]]
                logger.info("RAG catalog semantic candidate titles: %s", semantic_titles)
                logger.info("RAG catalog keyword candidate titles: %s", keyword_titles)

            merged = []
            seen_keys = set()
            merge_order = [*keyword_candidates, *strong_semantic, *relaxed_semantic] if catalog_query else [*strong_semantic, *relaxed_semantic, *keyword_candidates]
            for item in merge_order:
                key = (
                    str(item.get("url", "") or ""),
                    str(item.get("title", "") or ""),
                    str(item.get("content", "") or "")[:180],
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                merged.append(item)

            if catalog_query:
                merged_titles = [str(item.get("title", "") or "") for item in merged[:10]]
                logger.info("RAG catalog merged top 10 titles (pre-clean): %s", merged_titles)

            target_limit = max(3, int(top_k) if top_k else 5)
            reranked = self._apply_result_filters(query, merged, limit=target_limit)

            if catalog_query:
                reranked = self._catalog_rerank_candidates(reranked, limit=target_limit, query=query)

            if reranked:
                logger.info(
                    "Retrieval[hybrid-reranked] semantic=%s keyword=%s returned=%s for query: %s",
                    len(relaxed_semantic),
                    len(keyword_candidates),
                    len(reranked),
                    query[:80],
                )
                return reranked

            logger.info("Hybrid reranking returned 0; using keyword fallback")
            keyword_results = self._keyword_search(query, max(top_k * 20, 200))
            keyword_results = self._apply_result_filters(query, keyword_results, limit=5)
            logger.info("Retrieval[keyword] returned %s chunks", len(keyword_results))
            return keyword_results

        except Exception as e:
            logger.error(f"Semantic search failed: {e}, falling back to keyword search")
            keyword_results = self._keyword_search(query, top_k)
            keyword_results = self._apply_result_filters(query, keyword_results, limit=5)
            logger.info("Retrieval[keyword-error-fallback] returned %s chunks", len(keyword_results))
            return keyword_results

    def _keyword_search(self, query: str, top_k: int = 5) -> list[dict]:
        """Broadened keyword search using full-text + icontains fallback."""
        base_qs = self._quality_filtered_queryset()
        collected_by_chunk: dict[int, dict] = {}
        seen_ids = set()
        catalog_query = self._is_catalog_query(query)
        tokens = self._query_tokens(query)
        raw_tokens = self._raw_query_tokens(query)
        expanded_terms = self._expand_query_terms(query, tokens)
        if catalog_query:
            expanded_terms = list(dict.fromkeys([*expanded_terms, *CATALOG_EXPANSION_TERMS]))
        raw_all_terms = list(dict.fromkeys([query.strip(), *raw_tokens, *expanded_terms]))
        all_terms = list(dict.fromkeys([self._normalize_text(term) for term in raw_all_terms if term]))
        search_text = " ".join(raw_all_terms)

        def catalog_keyword_score(title: str, content: str, url: str) -> float:
            blob = self._normalize_text(f"{title} {content} {url}")
            raw_content = str(content or "")
            url_lower = str(url or "").lower()
            score = 0.0

            if any(term in blob for term in ["fakulte", "fakulteler", "fakulteleri"]):
                score += 2.0
            if any(term in blob for term in ["bolum", "bolumler"]):
                score += 1.5
            if any(term in blob for term in ["lisans programi", "lisans programlari"]):
                score += 1.5
            if "akademik" in blob:
                score += 1.0
            if any(term in url_lower for term in ["/akademik/", "/lisans/", "/fakultesi", "/bolumler/"]):
                score += 1.5

            comma_like = (raw_content.count(",") + raw_content.count(";")) >= 2
            academic_term_hits = sum(
                1
                for term in ["tip", "eczacilik", "saglik", "muhendislik", "toplum", "bilimleri"]
                if term in blob
            )
            if comma_like and academic_term_hits >= 2:
                score += 1.0

            return score

        def is_bad_catalog_page(title: str, content: str, url: str) -> bool:
            blob = self._normalize_text(f"{title} {content} {url}")
            return any(term in blob for term in EARLY_CATALOG_DOWNRANK_TERMS)

        def collect_candidate(chunk: DocumentChunk, base_score: float, match_type: str) -> None:
            title = chunk.web_page.title or ""
            content = chunk.content or ""
            url = chunk.web_page.url or ""

            if catalog_query and is_bad_catalog_page(title, content, url):
                return

            keyword_score = catalog_keyword_score(title, content, url) if catalog_query else float(base_score)
            if catalog_query and keyword_score <= 0:
                return

            final_score = keyword_score if catalog_query else float(base_score)
            item = self._serialize_chunk(chunk, score=final_score, match_type=match_type)
            item["_keyword_score"] = round(keyword_score, 4)

            existing = collected_by_chunk.get(chunk.id)
            if not existing:
                collected_by_chunk[chunk.id] = item
                return

            if float(item.get("_keyword_score", 0.0) or 0.0) > float(existing.get("_keyword_score", 0.0) or 0.0):
                collected_by_chunk[chunk.id] = item
                return

            if float(item.get("score", 0.0) or 0.0) > float(existing.get("score", 0.0) or 0.0):
                collected_by_chunk[chunk.id] = item

        # 1) PostgreSQL full-text search
        try:
            vector = (
                SearchVector("web_page__url", weight="A")
                + SearchVector("web_page__title", weight="B")
                + SearchVector("web_page__category", weight="C")
                + SearchVector("content", weight="D")
            )
            search_query = SearchQuery(search_text, search_type="websearch")
            fts_matches = (
                base_qs
                .annotate(rank=SearchRank(vector, search_query))
                .filter(rank__gt=0)
                .order_by("-rank", "-token_count")[: max(top_k * 4, top_k)]
            )

            for chunk in fts_matches:
                lexical = self._weighted_lexical_score(chunk, all_terms)
                if lexical <= 0 and not catalog_query:
                    continue

                if chunk.id in seen_ids:
                    continue
                seen_ids.add(chunk.id)
                score = (0.7 * lexical) + (0.3 * float(chunk.rank))
                collect_candidate(chunk, score, "keyword-fts")
        except Exception as exc:
            logger.warning("Full-text keyword search unavailable, continuing with icontains: %s", exc)

        # 2) Broad icontains (query + expanded terms + title/url/category/metadata)
        q_filter = Q()
        query_clean = self._normalize_text(query.strip())
        if query_clean:
            q_filter |= Q(content__icontains=query_clean)
            q_filter |= Q(web_page__title__icontains=query_clean)
            q_filter |= Q(web_page__url__icontains=query_clean)
            q_filter |= Q(web_page__category__icontains=query_clean)
            q_filter |= Q(metadata__title__icontains=query_clean)
            q_filter |= Q(metadata__url__icontains=query_clean)
            q_filter |= Q(metadata__category__icontains=query_clean)

        for term in all_terms:
            q_filter |= Q(content__icontains=term)
            q_filter |= Q(web_page__title__icontains=term)
            q_filter |= Q(web_page__url__icontains=term)
            q_filter |= Q(web_page__category__icontains=term)
            q_filter |= Q(metadata__title__icontains=term)
            q_filter |= Q(metadata__url__icontains=term)
            q_filter |= Q(metadata__category__icontains=term)

        if q_filter.children:
            contains_matches = (
                base_qs
                .filter(q_filter)
                .order_by("-token_count", "-content_len", "id")[: max(top_k * 8, top_k)]
            )

            for chunk in contains_matches:
                if chunk.id in seen_ids:
                    continue
                seen_ids.add(chunk.id)

                lexical = self._weighted_lexical_score(chunk, all_terms)
                if lexical <= 0 and not catalog_query:
                    continue

                score = 0.2 + (0.8 * lexical)
                collect_candidate(chunk, score, "keyword-contains")

        collected = list(collected_by_chunk.values())

        if collected:
            if catalog_query:
                collected_sorted = sorted(
                    collected,
                    key=lambda item: (
                        float(item.get("_keyword_score", 0.0) or 0.0),
                        float(item.get("score", 0.0) or 0.0),
                    ),
                    reverse=True,
                )
                keyword_titles = [str(item.get("title", "") or "") for item in collected_sorted[:10]]
                logger.info("RAG catalog keyword top 10 after scoring: %s", keyword_titles)
            else:
                collected_sorted = sorted(
                    collected,
                    key=lambda item: float(item.get("score", 0.0) or 0.0),
                    reverse=True,
                )

            collected_sorted = sorted(
                collected_sorted,
                key=lambda item: (
                    float(item.get("_keyword_score", 0.0) or 0.0)
                    if catalog_query
                    else float(item.get("score", 0.0) or 0.0)
                ),
                reverse=True,
            )
            return collected_sorted[:top_k]

        # No fallback here: do not return unrelated chunks.
        logger.info("Retrieval[keyword] returned 0 chunks after strict filtering")
        return []

    def _query_aware_post_filter(self, query: str, results: list[dict]) -> list[dict]:
        """Query-specific hard filtering and re-scoring applied after context cleaning."""
        norm_q = self._normalize_text(query)

        # ── Step 1: Global hard noise filter ──────────────────────────────
        filtered: list[dict] = []
        for result in results:
            content_norm = self._normalize_text(str(result.get("content", "") or ""))
            if any(term in content_norm for term in HARD_NOISE_CONTENT_TERMS):
                continue
            filtered.append(result)
        if not filtered:
            filtered = results  # never drop everything

        # ── Step 2: Query-aware content filter ────────────────────────────
        if "kampus" in norm_q or "nerede" in norm_q or "adres" in norm_q:
            kampus_terms = ["kampus", "yerleske", "adres", "lokasyon", "istanbul", "atasehir", "uskudar", "kadikoy", "iletisim", "konum"]
            relevant = [
                r for r in filtered
                if any(t in self._normalize_text(str(r.get("content", "") or "")) for t in kampus_terms)
            ]
            if relevant:
                filtered = relevant

        elif "ne zaman" in norm_q or "kuruldu" in norm_q:
            founding_terms = ["kuruldu", "kurulan", "kurulus", "yil", "tarih"]
            relevant = [
                r for r in filtered
                if any(t in self._normalize_text(str(r.get("content", "") or "")) for t in founding_terms)
                or any(t in self._normalize_text(str(r.get("url", "") or "")) for t in ["hakkinda", "universite"])
            ]
            if relevant:
                filtered = relevant

        elif "nedir" in norm_q:
            # Remove list-style chunks (navigation dumps with multiple "Fakültesi" repetitions).
            filtered = [
                r for r in filtered
                if str(r.get("content", "") or "").count("Fakültesi") < 3
            ] or filtered  # fallback: keep all if nothing survives

        # ── Step 3: Department query boost / downrank ──────────────────────
        if "bolumleri" in norm_q:
            rescored: list[dict] = []
            for result in filtered:
                content = str(result.get("content", "") or "")
                score = float(result.get("score", 0.0) or 0.0)
                dept_hits = sum(1 for t in ["Mühendisliği", "Bölümü"] if t in content)
                if dept_hits:
                    score += 4.0
                if content.count("Fakültesi") >= 3:
                    score -= 3.0
                r = dict(result)
                r["score"] = round(score, 4)
                rescored.append(r)
            rescored.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
            filtered = rescored

        return filtered

    def build_context(self, query: str, top_k: Optional[int] = None) -> tuple[str, list[dict]]:
        """
        Build context string for the LLM from search results.

        Returns:
            Tuple of (context_string, source_list)
        """
        context_top_sources = max(1, int(getattr(settings, "RAG_CONTEXT_TOP_SOURCES", 3)))
        retrieval_query = _build_retrieval_query(query)
        catalog_query = self._is_catalog_query(retrieval_query)
        if catalog_query:
            retrieval_top_k = max(top_k or settings.RAG_TOP_K, context_top_sources * 8, 30)
        else:
            retrieval_top_k = max(top_k or settings.RAG_TOP_K, context_top_sources * 4)
        results = self.search(retrieval_query, retrieval_top_k)

        if not results:
            logger.warning("RAG build_context returned 0 chunks for query: %s", query[:80])
            return "", []

        cleaned_results = self._clean_results_for_context(retrieval_query, results)
        if cleaned_results:
            selected_results = cleaned_results
            logger.info(
                "RAG build_context returned %s cleaned chunks (raw=%s) for query: %s",
                len(selected_results),
                len(results),
                query[:80],
            )
        else:
            if catalog_query:
                selected_results = []
                logger.warning(
                    "RAG context cleaning removed all catalog chunks for query: %s; returning empty context",
                    query[:80],
                )
            else:
                selected_results = results[:context_top_sources]
                logger.warning(
                    "RAG context cleaning removed all chunks for query: %s; using raw fallback chunks=%s",
                    query[:80],
                    len(selected_results),
                )

        # ── Seed injection: keyword match + semantic fallback ──────────────────
        try:
            def _norm(s: str) -> str:
                return s.lower().translate(TR_CHAR_TRANSLATION)

            _STOP = {
                "kim", "ne", "var", "bir", "ve", "ile", "de", "da",
                "mi", "mu", "mu", "nedir", "neler", "hangi", "nasil", "icin", "hic",
                "olan", "veya", "gibi", "icin",
                # Generic info-seeking phrases
                "bilgi", "bilgisi", "hakkinda", "hakkindaki", "ver", "verin",
                "nelerdir", "anlat", "acikla", "soyle",
                # Generic structural words — keep singular/genitive forms but allow
                # plural "bolumler/bolumleri" so list queries find the catalog seed
                "bolum", "bolumu",
                "fakulte", "fakultesi", "fakulteler",
                "program", "programi", "programlar",
                "universite", "universitesi",
                # English filler words — prevent them from consuming key_words slots
                "the", "are", "what", "where", "when", "how", "who", "which",
                "tell", "give", "show", "does", "there", "about", "have",
                "can", "this", "that", "these", "those", "some", "any",
            }
            key_words = [
                w.strip("?!.,") for w in retrieval_query.split()
                if len(w.strip("?!.,")) >= 3 and _norm(w.strip("?!.,")) not in _STOP
            ][:6]
            key_words_norm = [_norm(w) for w in key_words]

            all_seeds = list(
                DocumentChunk.objects
                .filter(web_page__source="seed")
                .select_related("web_page")
            )

            best_chunk = None
            best_score = -1

            if key_words_norm:
                for chunk in all_seeds:
                    title_norm = _norm(chunk.web_page.title or "")
                    content_norm = _norm(chunk.content or "")[:200]
                    unique_mc = sum(1 for kw in key_words_norm if kw in title_norm or kw in content_norm)
                    title_mc = sum(1 for kw in key_words_norm if kw in title_norm)
                    score = unique_mc * 10 + title_mc
                    if score > best_score:
                        best_score = score
                        best_chunk = chunk

            if best_chunk and best_score >= 1:
                logger.info("RAG seed inject (keyword, score=%d): %s for query: %s",
                            best_score, best_chunk.web_page.title, query[:80])

            if best_chunk and best_score >= 1:
                best_url = best_chunk.web_page.url
                selected_results = [r for r in selected_results if r.get("url") != best_url]
                selected_results.insert(0, {
                    "chunk_id": best_chunk.id,
                    "url": best_url,
                    "title": best_chunk.web_page.title,
                    "content": best_chunk.content,
                    "score": 0.6,
                    "source": best_chunk.web_page.source,
                })
                if len(selected_results) > context_top_sources + 1:
                    selected_results = selected_results[:context_top_sources + 1]
        except Exception as e:
            logger.warning("RAG seed injection failed: %s", e)

        # ── Always ensure seed chunks appear first in context ──────────────────
        seeds_first = [r for r in selected_results if r.get("source") == "seed"]
        non_seeds = [r for r in selected_results if r.get("source") != "seed"]
        if seeds_first:
            selected_results = seeds_first + non_seeds
            # Always restrict to 1 source when a seed leads — small LLMs get confused
            # when authoritative seed answers are followed by noisy scraped chunks.
            selected_results = selected_results[:1]

        # ── Keyword supplement: if cleaned results don't mention key query terms,
        # add up to 2 chunks found via direct DB text search ─────────────────
        query_lower = retrieval_query.lower()
        supplement_needed = False
        if not catalog_query and selected_results:
            combined_text = " ".join(r.get("content", "") for r in selected_results).lower()
            important_words = [w for w in query_lower.split() if len(w) >= 4]
            if important_words and not any(w in combined_text for w in important_words[:2]):
                supplement_needed = True
        elif not catalog_query and not selected_results:
            supplement_needed = True

        if supplement_needed:
            try:
                from django.db.models import Q
                key_words = [w for w in retrieval_query.split() if len(w) >= 4][:4]
                selected_urls = {r.get("url", "") for r in selected_results}

                kw_filter = Q()
                for kw in key_words:
                    kw_filter |= Q(content__icontains=kw)
                    kw_filter |= Q(web_page__title__icontains=kw)

                # Seed chunks: match by title only to avoid false positives
                seed_title_filter = Q(web_page__source="seed")
                seed_kw_q = Q()
                for kw in key_words:
                    seed_kw_q |= Q(web_page__title__icontains=kw)
                seed_matches = (
                    DocumentChunk.objects
                    .filter(seed_title_filter & seed_kw_q)
                    .exclude(web_page__url__in=selected_urls)
                    .select_related("web_page")
                    .order_by("-token_count")[:4]
                )
                other_matches = (
                    DocumentChunk.objects
                    .filter(kw_filter)
                    .exclude(web_page__source="seed")
                    .exclude(web_page__url__in=selected_urls)
                    .select_related("web_page")
                    .order_by("-id")[:3]
                )

                added = 0
                for chunk in [*seed_matches, *other_matches]:
                    if chunk.web_page.url in selected_urls:
                        continue
                    selected_urls.add(chunk.web_page.url)
                    entry = {
                        "chunk_id": chunk.id,
                        "url": chunk.web_page.url,
                        "title": chunk.web_page.title,
                        "content": chunk.content,
                        "score": 0.5,
                        "source": chunk.web_page.source,
                    }
                    selected_results.append(entry)
                    added += 1
                    if len(selected_results) >= context_top_sources:
                        break
                if added:
                    logger.info("RAG keyword supplement added %s chunks for query: %s", added, query[:80])
            except Exception as e:
                logger.warning("RAG keyword supplement failed: %s", e)


        if not selected_results:
            return "", []

        debug_titles = [str(r.get("title", "") or "") for r in selected_results]
        logger.info("RAG filtered context titles: %s", debug_titles)

        context_parts = []
        sources = []

        for i, result in enumerate(selected_results, 1):
            context_parts.append(
                f"### Kaynak {i}: {result['title']}\n"
                f"URL: {result['url']}\n"
                f"Benzerlik Skoru: {result['score']}\n\n"
                f"{result['content']}\n"
            )

            # sources must represent only the exact cleaned/used chunks.
            sources.append({
                "url": result["url"],
                "title": result["title"],
                "score": result["score"],
            })

        context = "\n---\n".join(context_parts)
        return context, sources

    # ── Stats ────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get RAG system statistics."""
        total_pages = WebPage.objects.count()
        processed_pages = WebPage.objects.filter(is_processed=True).count()
        pending_pages = WebPage.objects.filter(is_processed=False).count()
        total_chunks = DocumentChunk.objects.count()
        embedded_chunks = DocumentChunk.objects.filter(embedding__isnull=False).count()

        return {
            "total_pages": total_pages,
            "processed_pages": processed_pages,
            "pending_pages": pending_pages,
            "total_chunks": total_chunks,
            "embedded_chunks": embedded_chunks,
            "coverage": f"{processed_pages}/{total_pages}" if total_pages > 0 else "0/0",
        }


# Module-level singleton
rag_service = RAGService()





