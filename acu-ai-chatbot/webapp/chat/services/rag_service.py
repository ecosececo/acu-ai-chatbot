"""
RAG Service — Retrieval-Augmented Generation using pgvector.
Handles document chunking, embedding storage, and semantic search.
"""

import logging
import re
from typing import Optional

from django.conf import settings
from django.db import connection
from pgvector.django import CosineDistance

from ..models import DocumentChunk, WebPage
from .llm_service import llm_service

logger = logging.getLogger(__name__)

RAG_CONTEXT_MAX_CHARS = 9000
RAG_CONTEXT_TOP_SOURCES = 3
RAG_CONTEXT_CHARS_PER_SOURCE = 3000
RAG_CONTEXT_SOURCE_BUDGETS = (6500, 1800, 700)

# ── Türkçe Karakter Normalizasyonu ──────────────────────
# Kullanıcılar İngilizce klavyeyle Türkçe yazarken eksik özel karakterleri tamamlar.
# Bu tablo SADECE query-time'da uygulanır; veritabanındaki metinlere dokunulmaz.
_TR_ASCII_MAP: dict[str, str] = {
    # Kelimenin içindeki örüntüler (uzun → kısa sırayla kontrol edilir)
    "gh":  "ğ",   # baglantı → bağlantı  (ama 'gh' Türkçe'de nadir — sadece 'g' ikilisi varsa)
    "sh":  "ş",   # shirket → şirket (nadir)
}

# Kelime bazlı tam eşleşme tablosu — daha güvenli
_TR_WORD_MAP: dict[str, str] = {
    # ── Özel isimler ────────────────────────
    "acibadem":          "acıbadem",
    "acibademi":         "acıbademi",
    "acibadem'de":       "acıbadem'de",
    "atasehir":          "ataşehir",
    "kayisdagi":         "kayışdağı",
    # ── ğ eksik ─────────────────────────────
    "muhendis":          "mühendis",
    "muhendislik":       "mühendislik",
    "muhendisligi":      "mühendisliği",
    "muhendisliginde":   "mühendisliğinde",
    "muhendisliginin":   "mühendisliğinin",
    "muhendisin":        "mühendisin",
    "ogretim":           "öğretim",
    "ogrenci":           "öğrenci",
    "ogrenciler":        "öğrenciler",
    "ogrencinin":        "öğrencinin",
    "ogrencilerin":      "öğrencilerin",
    "ogrenim":           "öğrenim",
    "ogranimi":          "öğrenimi",
    "ogretmen":          "öğretmen",
    "ogretmeni":         "öğretmeni",
    "dogrulama":         "doğrulama",
    "dogru":             "doğru",
    "baglanti":          "bağlantı",
    "saglik":            "sağlık",
    "saglıklı":          "sağlıklı",
    "yuksek":            "yüksek",
    "agirlik":           "ağırlık",
    "diger":             "diğer",
    "digerleri":         "diğerleri",
    # ── ş eksik ─────────────────────────────
    "baskanligi":        "başkanlığı",
    "baskanlik":         "başkanlık",
    "baskan":            "başkan",
    "basvuru":           "başvuru",
    "basvurusu":         "başvurusu",
    "basvurular":        "başvurular",
    "basvurulari":       "başvuruları",
    "basvurabilir":      "başvurabilir",
    "basvurabilirim":    "başvurabilirim",
    "basvurabilirsiniz": "başvurabilirsiniz",
    "basvurabilmek":     "başvurabilmek",
    "basvurmak":         "başvurmak",
    "basvurdum":         "başvurdum",
    "arastirma":         "araştırma",
    "arastirmaci":       "araştırmacı",
    "simdiki":           "şimdiki",
    "simdi":             "şimdi",
    "sube":              "şube",
    "sehir":             "şehir",
    "kosul":             "koşul",
    "kosullar":          "koşullar",
    "kosullari":         "koşulları",
    "egitim":            "eğitim",
    "egitimi":           "eğitimi",
    "egitime":           "eğitime",
    "egitimde":          "eğitimde",
    "egitimler":         "eğitimler",
    "egitimleri":        "eğitimleri",
    "islem":             "işlem",
    "islemi":            "işlemi",
    "islemleri":         "işlemleri",
    "isin":              "işin",
    # ── ö eksik ─────────────────────────────
    "ozel":              "özel",
    "oneri":             "öneri",
    "oneriler":          "öneriler",
    # ── ü eksik ─────────────────────────────
    "universite":        "üniversite",
    "universitesi":      "üniversitesi",
    "universitemiz":     "üniversitemiz",
    "universitede":      "üniversitede",
    "universitenin":     "üniversitenin",
    "ucret":             "ücret",
    "ucreti":            "ücreti",
    "ucretler":          "ücretler",
    "ucretleri":         "ücretleri",
    "uye":               "üye",
    "uyesi":             "üyesi",
    "uyeler":            "üyeler",
    "uyeleri":           "üyeleri",
    "mufredat":          "müfredat",
    "mufredati":         "müfredatı",
    # ── ı eksik ─────────────────────────────
    "bolum":             "bölüm",
    "bolumu":            "bölümü",
    "bolumler":          "bölümler",
    "bolumleri":         "bölümleri",
    "kisaltma":          "kısaltma",
    "kismi":             "kısmi",
    # ── ç eksik ─────────────────────────────
    "icerik":            "içerik",
    "icerigi":           "içeriği",
    "gecis":             "geçiş",
    "gecisi":            "geçişi",
    "gecisler":          "geçişler",
    "harc":              "harç",
    "harci":             "harcı",
    # ── Çoğul / türemiş formlar ──────────────
    "lisansustu":        "lisansüstü",
    "fakulte":           "fakülte",
    "fakultesi":         "fakültesi",
    "fakulteler":        "fakülteler",
    "fakultelerinde":    "fakültelerinde",
    "kutuphane":         "kütüphane",
    "kutuphanesi":       "kütüphanesi",
    "kulup":             "kulüp",
    "kulupler":          "kulüpler",
    "kulupleri":         "kulüpleri",
    "kayit":             "kayıt",
    "kayitlar":          "kayıtlar",
    "kayitlari":         "kayıtları",
    "iletisim":          "iletişim",
    "iletisimde":        "iletişimde",
    "sinav":             "sınav",
    "sinavlar":          "sınavlar",
    "sinavlari":         "sınavları",
    "devamsizlik":       "devamsızlık",
    "yerlesme":          "yerleşme",
    "yerlesim":          "yerleşim",
    "yerlestirme":       "yerleştirme",
    "yatay gecis":       "yatay geçiş",
    "dikey gecis":       "dikey geçiş",
}


def normalize_turkish_query(query: str) -> str:
    """
    Kullanıcının İngilizce karakterlerle yazdığı Türkçe sorguyu,
    doğru Türkçe karakterlere normalize eder.

    Örnek: 'bilgisayar muhendisligi' → 'bilgisayar mühendisliği'

    SADECE query-time'da kullanılır; veritabanındaki metinlere dokunulmaz.
    Hem semantic search'e hem FTS'e normalize edilmiş hali gönderilir.
    """
    words = query.split()
    normalized_words = []
    for word in words:
        lower = word.lower()
        if lower in _TR_WORD_MAP:
            # Orijinal büyük/küçük harfini koru (ilk harf büyükse normalize de büyük)
            mapped = _TR_WORD_MAP[lower]
            if word[0].isupper() and mapped:
                mapped = mapped[0].upper() + mapped[1:]
            normalized_words.append(mapped)
            logger.debug(f"Normalized: '{word}' → '{mapped}'")
        else:
            normalized_words.append(word)
    result = " ".join(normalized_words)
    if result != query:
        logger.info(f"Turkish normalization: '{query}' → '{result}'")
    return result

# ── Text Chunking ────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> list[str]:
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
            # Convert char-based overlap to word count (~5 chars/word for Turkish)
            overlap_word_count = max(1, overlap // 5)
            words = current_chunk.split()
            overlap_words = words[-overlap_word_count:] if len(words) > overlap_word_count else words
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


_NAV_NOISE = re.compile(
    r"ana içeriğe atla|ana gezinti menüsü|"
    r"(• üniversite|• öğrenci|• akademik).*(• araştırma|• international)",
    re.I | re.S,
)


def _is_nav_chunk(content: str) -> bool:
    """Return True if chunk is mostly navigation/menu noise, not real content."""
    return bool(_NAV_NOISE.search(content))


class RAGService:
    """
    Retrieval-Augmented Generation service.
    Handles the full pipeline: chunk → embed → store → retrieve → augment.
    """

    # ── Query Expansion Map ──────────────────────────────
    QUERY_EXPANSIONS = {
        "ücret": "öğrenim ücreti harç fiyat ödeme taksit",
        "ucret": "öğrenim ücreti harç fiyat ödeme taksit",
        "burs": "burs indirim başarı bursu tam burs muafiyet",
        "yatay geçiş": "yatay geçiş kontenjan başvuru koşulları not ortalaması",
        "yatay gecis": "yatay geçiş kontenjan başvuru koşulları not ortalaması",
        "dikey geçiş": "dikey geçiş DGS kontenjan başvuru koşulları",
        "dikey gecis": "dikey geçiş DGS kontenjan başvuru koşulları",
        "erasmus": "erasmus değişim programı yurtdışı anlaşmalı üniversite",
        "kayıt": "kayıt işlemleri belge evrak başvuru kabul",
        "kayit": "kayıt işlemleri belge evrak başvuru kabul",
        "mezuniyet": "mezuniyet diploma tez bitirme projesi",
        "yemekhane": "yemekhane yemek kafeterya kantin menü",
        "kütüphane": "kütüphane kitap kaynak veritabanı çalışma",
        "kutuphane": "kütüphane kitap kaynak veritabanı çalışma",
        "yurt": "yurt barınma konaklama öğrenci evi",
        "staj": "staj zorunlu staj yaz stajı işyeri eğitimi",
        "kredi": "kredi AKTS ders saati teorik uygulama",
        "müfredat": "müfredat ders planı program çıktıları öğretim planı",
        "mufredat": "müfredat ders planı program çıktıları öğretim planı",
        "kontenjan": "kontenjan başarı sıralaması taban puanı yerleştirme",
        "akademik takvim": "akademik takvim dönem başlangıç bitiş sınav tarihleri",
        "kulüp": "kulüp topluluk öğrenci kulüpleri aktivite etkinlik",
        "kulup": "kulüp topluluk öğrenci kulüpleri aktivite etkinlik",
        "topluluk": "topluluk kulüp öğrenci kulüpleri etkinlik",
        "fakülte": "fakülte bölüm program lisans akademik birim",
        "fakülteler": "fakülteler bölümler lisans akademik birimler",
        "fakulte": "fakülte bölüm program lisans akademik birim",
        "fakulteler": "fakülteler bölümler lisans akademik birimler",
        "bölüm": "bölüm fakülte program lisans akademik birim",
        "bölümler": "bölümler fakülteler programlar lisans",
        "bolum": "bölüm fakülte program lisans akademik birim",
        "bolumler": "bölümler fakülteler programlar lisans",
        "program": "program bölüm fakülte lisans lisansüstü yüksek lisans doktora",
        "spor": "spor fitness merkezi salon etkinlik",
        "etkinlik": "etkinlik seminer konferans workshop toplantı",
        "muhendis": "mühendislik mühendis bilgisayar yazılım elektrik makine",
        "mühendis": "mühendislik mühendis bilgisayar yazılım elektrik makine",
        "ogrenci": "öğrenci öğrenciler öğrenim kayıt",
        "öğrenci": "öğrenci öğrenciler öğrenim kayıt",
        "universite": "üniversite fakülte bölüm kampüs",
        "üniversite": "üniversite fakülte bölüm kampüs",
        "basvuru": "başvuru kayıt kabul koşulları belgeler",
        "başvuru": "başvuru kayıt kabul koşulları belgeler",
        "ogretim": "öğretim üyesi akademisyen profesör",
        "yuksek lisans": "yüksek lisans lisansüstü tezli tezsiz",
        "yüksek lisans": "yüksek lisans lisansüstü tezli tezsiz",
        "yuksek": "yüksek lisans lisansüstü",
        "lisansustu": "lisansüstü yüksek lisans doktora enstitü",
        "lisansüstü": "lisansüstü yüksek lisans doktora enstitü",
        "egitim": "eğitim öğretim program ders",
        "ingilizce": "ingilizce english İngilizce lisans yüksek lisans program",
        "kampus": "kampüs ataşehir kerem aydınlar kampüs",
        "kampüs": "kampüs ataşehir kerem aydınlar",
    }

    # ── Category Detection Patterns ──────────────────────
    CATEGORY_PATTERNS = {
        "admission": ["başvuru", "kayıt", "aday", "ücret", "burs", "kontenjan",
                       "taban puan", "yerleştirme", "harç", "indirim"],
        "academic": ["ders", "kredi", "müfredat", "akts", "program", "not",
                      "sınav", "devamsızlık", "transkript", "akademik takvim"],
        "department": ["fakülte", "bölüm", "dekan", "mühendislik", "tıp",
                        "eczacılık", "sağlık", "enstitü"],
        "campus": ["kampüs", "yemekhane", "kütüphane", "spor", "kulüp",
                    "yurt", "barınma", "ulaşım", "topluluk", "etkinlik", "fitness"],
        "student": ["öğrenci", "erasmus", "staj", "mezuniyet", "diploma",
                     "yatay geçiş", "dikey geçiş"],
        "research": ["araştırma", "yayın", "proje", "laboratuvar"],
        "contact": ["iletişim", "adres", "telefon", "e-posta", "ulaşım"],
    }

    def __init__(self):
        self._ensure_pgvector()

    def _ensure_pgvector(self):
        """Ensure pgvector extension is installed in PostgreSQL."""
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        except Exception as e:
            logger.warning(f"Could not create pgvector extension: {e}")

    # ── Query Enhancement ────────────────────────────────

    def _rewrite_query(self, query: str) -> str:
        """Expand short/ambiguous queries with related terms for better retrieval."""
        query_lower = query.lower()
        expansions = []
        for key, expansion in self.QUERY_EXPANSIONS.items():
            if key in query_lower:
                expansions.append(expansion)

        if expansions:
            expanded = f"{query} {' '.join(expansions)}"
            logger.debug(f"Query expanded: '{query}' → '{expanded[:100]}...'")
            return expanded
        return query

    def _detect_category(self, query: str) -> Optional[str]:
        """Detect the most likely category from user query."""
        query_lower = query.lower()
        best_category = None
        best_score = 0

        for category, keywords in self.CATEGORY_PATTERNS.items():
            score = sum(1 for kw in keywords if kw in query_lower)
            if score > best_score:
                best_score = score
                best_category = category

        if best_score >= 2:
            logger.debug(f"Detected category: {best_category} (score: {best_score})")
            return best_category
        return None

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
            # Prefix with page title so embeddings know the source context
            title_prefix = f"[{webpage.title}]\n" if webpage.title else ""
            enriched_content = title_prefix + chunk_text_content

            # Generate embedding from enriched content
            embedding = llm_service.get_embedding(enriched_content)

            DocumentChunk.objects.create(
                web_page=webpage,
                chunk_index=i,
                content=enriched_content,
                embedding=embedding,
                token_count=len(enriched_content.split()),
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

    # ── Retrieval ────────────────────────────────────────

    def search(self, query: str, top_k: Optional[int] = None) -> list[dict]:
        """
        Perform enhanced search using hybrid (semantic + keyword) strategy
        with query expansion, category filtering, and re-ranking.

        Returns:
            List of dicts with keys: content, url, title, source, score
        """
        if top_k is None:
            top_k = getattr(settings, 'RAG_TOP_K', 8)

        # Step 0: Normalize Turkish characters (e.g. muhendis → mühendis)
        normalized_query = normalize_turkish_query(query)

        # Step 1: Expand query for better retrieval
        expanded_query = self._rewrite_query(normalized_query)

        # Step 2: Detect category for optional filtering
        category = self._detect_category(normalized_query)

        # Step 3: Hybrid search
        # Semantic: expanded normalized query (synonyms + correct chars → better embedding match)
        semantic_results = self._semantic_search(expanded_query, top_k * 8, category)
        # FTS: normalized query — Postgres Turkish stemmer requires proper ğ/ş/ı/ö/ü/ç chars
        keyword_results = self._keyword_search(normalized_query, top_k * 8, category)

        # Step 4: Merge results using Reciprocal Rank Fusion
        merged = self._reciprocal_rank_fusion(semantic_results, keyword_results, top_k * 3)

        # Step 5: Re-rank
        reranked = self._rerank(normalized_query, merged, top_k)

        # Step 6: Normalize scores
        if reranked:
            max_score = reranked[0]["score"]
            if max_score > 0:
                for r in reranked:
                    r["score"] = round((r["score"] / max_score) * 0.95, 4)

        logger.info(
            f"Search pipeline: query='{query[:50]}' "
            f"normalized='{normalized_query[:50]}' "
            f"category={category} semantic={len(semantic_results)} "
            f"keyword={len(keyword_results)} merged={len(merged)} "
            f"final={len(reranked)}"
        )

        return reranked

    def _semantic_search(
        self, query: str, top_k: int, category: Optional[str] = None
    ) -> list[dict]:
        """Perform semantic search using pgvector cosine similarity."""
        query_embedding = llm_service.get_embedding(query)
        if query_embedding is None:
            logger.warning("Could not generate query embedding")
            return []

        try:
            qs = DocumentChunk.objects.filter(embedding__isnull=False)

            results = (
                qs.annotate(distance=CosineDistance("embedding", query_embedding))
                .order_by("distance")[:top_k]
            )

            search_results = []
            for chunk in results:
                score = 1 - chunk.distance
                if score >= settings.RAG_SIMILARITY_THRESHOLD and len(chunk.content) >= 50 and not _is_nav_chunk(chunk.content):
                    search_results.append({
                        "content": chunk.content,
                        "url": chunk.metadata.get("url", ""),
                        "title": chunk.metadata.get("title", ""),
                        "source": chunk.metadata.get("source", ""),
                        "category": chunk.metadata.get("category", ""),
                        "score": round(score, 4),
                    })

            return search_results

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

    def _keyword_search(
        self, query: str, top_k: int = 5, category: Optional[str] = None
    ) -> list[dict]:
        """Keyword-based search using PostgreSQL Full-Text Search."""
        from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
        
        vector = SearchVector('content', config='turkish')
        search_query = SearchQuery(query, config='turkish')
        
        qs = (
            DocumentChunk.objects
            .annotate(rank=SearchRank(vector, search_query))
            .filter(rank__gt=0.01)
            .order_by("-rank")
        )

        results = qs.select_related("web_page")[:top_k]

        return [
            {
                "content": chunk.content,
                "url": chunk.metadata.get("url", chunk.web_page.url),
                "title": chunk.metadata.get("title", chunk.web_page.title),
                "source": chunk.metadata.get("source", chunk.web_page.source),
                "category": chunk.metadata.get("category", ""),
                "score": round(getattr(chunk, "rank", 0.0), 4),
            }
            for chunk in results
            if len(chunk.content) >= 50 and not _is_nav_chunk(chunk.content)
        ]

    def _reciprocal_rank_fusion(
        self,
        semantic_results: list[dict],
        keyword_results: list[dict],
        top_k: int,
        k: int = 60,
    ) -> list[dict]:
        """Merge semantic and keyword results using Reciprocal Rank Fusion."""
        scores: dict[str, float] = {}
        content_map: dict[str, dict] = {}

        semantic_scores = {}
        for rank, result in enumerate(semantic_results):
            key = result["content"][:200]
            score = 1.0 / (k + rank + 1)
            if key not in semantic_scores or score > semantic_scores[key]:
                semantic_scores[key] = score
                content_map[key] = result

        keyword_scores = {}
        for rank, result in enumerate(keyword_results):
            key = result["content"][:200]
            score = 4.0 / (k + rank + 1)
            if key not in keyword_scores or score > keyword_scores[key]:
                keyword_scores[key] = score
                if key not in content_map:
                    content_map[key] = result

        for key in content_map.keys():
            scores[key] = semantic_scores.get(key, 0) + keyword_scores.get(key, 0)

        sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:top_k]

        merged = []
        for key in sorted_keys:
            result = content_map[key].copy()
            result["score"] = round(scores[key], 4)
            merged.append(result)

        return merged

    def _rerank(self, query: str, results: list[dict], top_k: int) -> list[dict]:
        """
        Re-rank results based on keyword density overlap with the normalized query.
        """
        if not results:
            return []

        query_words = set(w.lower() for w in query.split() if len(w) > 2)
        ascii_query_words = set(w.lower() for w in normalize_turkish_query(query).split() if len(w) > 2)
        all_query_words = query_words | ascii_query_words
        query_lower = query.lower()
        course_query = any(
            kw in query_lower
            for kw in ("ders", "ders program", "dersler", "mufredat", "müfredat")
        )
        # Lisans program sorgusu — doktora/yükseklisans kaynaklarını bastır
        lisans_query = any(
            kw in query_lower
            for kw in ("ingilizce", "english", "lisans program", "hangi program", "hangi bölüm",
                       "fakülte", "fakulte", "bölüm", "bolum")
        )
        # Konum sorgusu
        location_query = any(
            kw in query_lower
            for kw in ("nerede", "adres", "kampüs", "kampus", "konum", "atasehir", "ataşehir")
        )

        for result in results:
            content_lower = result["content"].lower()
            title_lower = result.get("title", "").lower()
            url_lower = result.get("url", "").lower()
            # Count how many query words appear in the content (normalized + raw union)
            match_count = sum(1 for w in all_query_words if w in content_lower)
            keyword_boost = match_count / max(len(all_query_words), 1)
            # Extra boost if query words appear in the page TITLE (2x weight)
            title_match = sum(1 for w in all_query_words if w in title_lower)
            title_boost = title_match / max(len(all_query_words), 1) * 2.0
            course_boost = 0.0
            if course_query:
                if "dersler" in title_lower or "courses" in url_lower or "progcourses" in url_lower:
                    course_boost += 3.0
                if result.get("source") == "bologna":
                    course_boost += 1.0
                if "genel bilgiler" in title_lower or "program hakk" in title_lower:
                    course_boost -= 0.5
            # Lisans program sorgusu: doktora sayfalarını bastır, lisans/ingilizce sayfaları yükselt
            if lisans_query:
                if "doktora" in url_lower or "doktora" in title_lower:
                    course_boost -= 1.5
                if "/lisans/" in url_lower or "lisans-program" in url_lower:
                    course_boost += 0.5
                if "ingilizce" in title_lower or "english" in title_lower:
                    course_boost += 1.0
            # Konum sorgusu: kampüs sayfalarını öne al
            if location_query:
                if "kampus" in url_lower or "campus" in url_lower or "atasehir" in url_lower:
                    course_boost += 2.0
            result["score"] = round(result["score"] * (1 + keyword_boost + title_boost + course_boost), 4)



        # Re-sort and return top_k
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def build_context(self, query: str, top_k: Optional[int] = None) -> tuple[str, list[dict]]:
        """
        Build context string for the LLM from search results.

        Returns:
            Tuple of (context_string, source_list)
        """
        results = self.search(query, top_k)

        if not results:
            return "", []

        context_parts = []
        sources = []
        seen_urls = set()
        used_chars = 0

        grouped_results = []
        for result in results:
            url = result["url"]
            existing = next((item for item in grouped_results if item["url"] == url), None)
            if existing:
                existing["chunks"].append(result["content"])
                existing["score"] = max(existing["score"], result["score"])
            else:
                grouped_results.append({
                    "url": url,
                    "title": result["title"],
                    "score": result["score"],
                    "chunks": [result["content"]],
                })

        for i, result in enumerate(grouped_results[:RAG_CONTEXT_TOP_SOURCES], 1):
            content = "\n\n".join(result["chunks"])
            source_budget = RAG_CONTEXT_SOURCE_BUDGETS[i - 1] if i <= len(RAG_CONTEXT_SOURCE_BUDGETS) else RAG_CONTEXT_CHARS_PER_SOURCE
            if len(content) > source_budget:
                content = content[:source_budget].rsplit("\n", 1)[0].strip()
            if used_chars + len(content) > RAG_CONTEXT_MAX_CHARS:
                content = content[:max(0, RAG_CONTEXT_MAX_CHARS - used_chars)].strip()
            if not content:
                break
            used_chars += len(content)
            context_parts.append(
                f"### Kaynak {i}: {result['title']}\n"
                f"URL: {result['url']}\n"
                f"{content}\n"
            )

            if result["url"] not in seen_urls:
                sources.append({
                    "url": result["url"],
                    "title": result["title"],
                    "score": result["score"],
                })
                seen_urls.add(result["url"])

        context = "\n---\n".join(context_parts)
        return context, sources

    # ── Stats ────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get RAG system statistics."""
        total_pages = WebPage.objects.count()
        processed_pages = WebPage.objects.filter(is_processed=True).count()
        total_chunks = DocumentChunk.objects.count()
        embedded_chunks = DocumentChunk.objects.filter(embedding__isnull=False).count()

        return {
            "total_pages": total_pages,
            "processed_pages": processed_pages,
            "total_chunks": total_chunks,
            "embedded_chunks": embedded_chunks,
            "coverage": f"{processed_pages}/{total_pages}" if total_pages > 0 else "0/0",
        }


# Module-level singleton
rag_service = RAGService()






