"""
ACU Main Website Scraper — Scrapes content from acibadem.edu.tr

Responsible scraping with delays and rate limiting.
Collects: faculty info, departments, admission, campus, contact, news.
"""

import logging
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from django.conf import settings
from chat.models import WebPage

logger = logging.getLogger(__name__)

MAIN_CONTENT_SELECTORS = [
    # ACU-specific primary content container (Drupal Bootstrap theme)
    ".sidebar-page-content",
    ".col-lg-9.col-12",
    # Generic fallbacks
    "article",
    ".field--name-body",
    ".node__content",
    ".page-content",
    "#content",
    "#main-content",
    "[role='main']",
]

UNWANTED_SELECTORS = [
    "script",
    "style",
    "noscript",
    "iframe",
    "nav",
    "header",
    "footer",
    # ACU-specific noise containers
    ".sidebar-menu-wrapper",
    ".main-menu-wrap",
    ".mega-wrapper",
    ".mobil-mega-wrapper",
    ".header-top-search",
    ".accordion",
    ".breadcrumb",
    ".mobil-breadcrumb",
]

NOISE_PHRASES = [
    "tanitim katalogu",
    "sanal tur",
    "komisyonlar",
    "kurul ve komisyonlar",
    "hizli erisim",
    "quick links",
    "ilgili linkler",
    "related links",
    "menu",
    "navigasyon",
    "duyurular",
]

CONTENT_NOISE_TERMS = [
    "tanitim",
    "video",
    "etkinlik",
    "duyuru",
]

# URLs to skip
SKIP_PATTERNS = [
    r"\.pdf$",
    r"\.jpg$",
    r"\.png$",
    r"\.gif$",
    r"\.mp4$",
    r"\.zip$",
    r"\.doc$",
    r"\.xls$",
    r"javascript:",
    r"mailto:",
    r"tel:",
    r"#$",
    r"/en/",  # Skip English pages initially, focus on Turkish
    r"login",
    r"signin",
    r"auth",
]

# Important seed URLs to start with
_BASE = "https://www.acibadem.edu.tr"
_AK = f"{_BASE}/akademik/lisans"

SEED_URLS = [
    # Ana sayfalar
    f"{_BASE}/",
    f"{_BASE}/universite/hakkinda",
    f"{_BASE}/universite/tarihce",
    f"{_BASE}/universite/misyon-vizyon",
    f"{_BASE}/universite/hakkinda/universite-yonetimi",
    f"{_BASE}/akademik",
    f"{_BASE}/akademik/lisans",
    f"{_BASE}/iletisim",

    # Fakülteler — ana sayfalar
    f"{_AK}/tip-fakultesi",
    f"{_AK}/tip-fakultesi/hakkinda",
    f"{_AK}/tip-fakultesi/bolumler",
    f"{_AK}/tip-fakultesi/ders-programi",
    f"{_AK}/eczacilik-fakultesi",
    f"{_AK}/eczacilik-fakultesi/hakkinda",
    f"{_AK}/eczacilik-fakultesi/bolumler",
    f"{_AK}/eczacilik-fakultesi/ders-programlari",
    f"{_AK}/saglik-bilimleri-fakultesi",
    f"{_AK}/saglik-bilimleri-fakultesi/hakkinda",
    f"{_AK}/saglik-bilimleri-fakultesi/bolumler",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/hakkinda",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/bolumler",

    # Mühendislik bölümleri
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/bilgisayar-muhendisligi",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/bilgisayar-muhendisligi/hakkinda",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/bilgisayar-muhendisligi/ders-programi",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/yazilim-muhendisligi",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/yazilim-muhendisligi/hakkinda",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/biyomedikal-muhendisligi",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/endustri-muhendisligi",
    f"{_AK}/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/molekuler-biyoloji-ve-genetik",

    # Sağlık Bilimleri bölümleri
    f"{_AK}/saglik-bilimleri-fakultesi/bolumler/hemsirelik",
    f"{_AK}/saglik-bilimleri-fakultesi/bolumler/fizyoterapi-ve-rehabilitasyon",
    f"{_AK}/saglik-bilimleri-fakultesi/bolumler/beslenme-ve-diyetetik",
    f"{_AK}/saglik-bilimleri-fakultesi/bolumler/odyoloji",
    f"{_AK}/saglik-bilimleri-fakultesi/bolumler/dil-ve-konusma-terapisi",
    f"{_AK}/saglik-bilimleri-fakultesi/bolumler/sosyal-hizmet",

    # Aday öğrenci / kabul / burs
    f"{_BASE}/aday/ogrenci",
    f"{_BASE}/aday/ogrenci/basvuru",
    f"{_BASE}/aday/ogrenci/ucretler",
    f"{_BASE}/aday/ogrenci/egitim/burs",
    f"{_BASE}/aday/ogrenci/egitim/burs/burs-olanaklari",
    f"{_BASE}/aday/ogrenci/egitim/burs/basari-bursu",
    f"{_BASE}/aday/ogrenci/kabul-kosullari",
    f"{_BASE}/aday/ogrenci/yatay-gecis",
    f"{_BASE}/aday/ogrenci/uluslararasi",

    # Öğrenci hizmetleri
    f"{_BASE}/ogrenci",
    f"{_BASE}/ogrenci/ogrenci-isleri",
    f"{_BASE}/ogrenci/acuda-yasam",
    f"{_BASE}/ogrenci/acuda-yasam/kutuphane",
    f"{_BASE}/ogrenci/acuda-yasam/spor",
    f"{_BASE}/ogrenci/ogrenci-topluluk-ve-kulupleri",

    # Lisansüstü
    f"{_BASE}/akademik/lisansustu",
    f"{_BASE}/saglik-bilimleri-enstitusu",
    f"{_BASE}/saglik-bilimleri-enstitusu/programlar",

    # Araştırma
    f"{_BASE}/arastirma",
    f"{_BASE}/universite/arastirma-merkezleri",
]


def _categorize_url(url: str) -> str:
    """Categorize URL based on its path."""
    path = urlparse(url).path.lower()

    category_patterns = {
        "faculty": [r"fakulte", r"faculty"],
        "department": [r"bolum", r"department", r"muhendislik", r"tip", r"eczacilik"],
        "program": [r"program", r"lisans", r"yukseklisans", r"doktora"],
        "admission": [r"aday", r"basvuru", r"kabul", r"admission", r"ucret", r"burs"],
        "campus": [r"kampus", r"campus", r"kutuphane", r"yemekhane", r"spor", r"kulup"],
        "about": [r"hakkimizda", r"about", r"tarihce", r"misyon", r"vizyon"],
        "contact": [r"iletisim", r"contact"],
        "academic": [r"akademik", r"academic", r"ders", r"course", r"mufredat"],
        "student": [r"ogrenci", r"student", r"erasmus", r"staj"],
        "news": [r"haber", r"duyuru", r"etkinlik", r"news"],
        "research": [r"arastirma", r"research", r"yayin", r"proje"],
    }

    for category, patterns in category_patterns.items():
        for pattern in patterns:
            if re.search(pattern, path):
                return category
    return "general"


def _should_skip_url(url: str) -> bool:
    """Check if URL should be skipped."""
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


def _extract_text_from_html(soup: BeautifulSoup) -> str:
    """Extract clean text content from parsed HTML."""
    date_only_re = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    date_any_re = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
    date_text_re = re.compile(
        r"^(\d{1,2}\s+(ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)\s+\d{4})$",
        re.IGNORECASE,
    )
    date_text_any_re = re.compile(
        r"\b\d{1,2}\s+(ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)\s+\d{4}\b",
        re.IGNORECASE,
    )

    def _normalize(text: str) -> str:
        text = (text or "").lower().strip()
        replacements = {
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
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        text = re.sub(r"\s+", " ", text)
        return text

    def _clean_node(node: BeautifulSoup) -> None:
        if node is None:
            return

        # Global structural cleanup first.
        for selector in UNWANTED_SELECTORS:
            for tag in list(node.select(selector)):
                if isinstance(tag, Tag):
                    tag.decompose()

    def _pick_main_content(node: BeautifulSoup):
        candidates = []
        for selector in MAIN_CONTENT_SELECTORS:
            for found in node.select(selector):
                text_len = len(found.get_text(" ", strip=True))
                if text_len > 120:
                    candidates.append((text_len, found))

        if candidates:
            # Prefer the longest meaningful content block.
            return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]

        body = node.body if node.body else node
        return body

    def _is_short_link_list_block(tag) -> bool:
        anchors = tag.find_all("a", href=True)
        if len(anchors) < 3:
            return False

        text = tag.get_text(" ", strip=True)
        non_link_text_len = len(text) - sum(len(a.get_text(" ", strip=True)) for a in anchors)

        # Mostly link items, very little explanatory prose.
        if non_link_text_len < 120:
            return True

        # UL/OL blocks with short items are usually navigation or quick links.
        if tag.name in {"ul", "ol"}:
            items = tag.find_all("li")
            if items and all(len(li.get_text(" ", strip=True)) < 90 for li in items):
                return True

        return False

    def _is_noise_text_block(text: str) -> bool:
        norm = _normalize(text)
        if not norm:
            return True
        return any(phrase in norm for phrase in NOISE_PHRASES)

    def _is_noise_line(text: str) -> bool:
        """Line-level noise removal while preserving core descriptive paragraphs."""
        clean = re.sub(r"\s+", " ", (text or "")).strip()
        if not clean:
            return True

        norm = _normalize(clean)

        # Drop date-only lines like 06/04/2026 or 17 Nisan 2026.
        if date_only_re.fullmatch(clean) or date_text_re.fullmatch(norm):
            return True

        # Drop event/news lines that include a date marker in-line.
        has_any_date = bool(date_any_re.search(clean) or date_text_any_re.search(norm))
        if has_any_date:
            if any(term in norm for term in ["fakultesi", "muhendisligi", "etkinlik", "duyuru", "arsiv", "prof"]):
                return True
            if len(clean) < 280:
                return True

        # Remove short promotional/event/menu-like lines.
        if any(term in norm for term in CONTENT_NOISE_TERMS):
            if len(clean) < 220:
                return True

        if "devamini oku" in norm:
            return True

        words = [w for w in clean.split() if w]

        # Remove short heading-like labels with no explanatory body.
        if len(words) < 4 and len(clean) < 50:
            return True

        # Paragraph filter: keep meaningful sentence-like lines.
        if len(clean) < 40:
            return True

        # Keep long explanatory lines; short lines should at least look sentence-like.
        if len(clean) < 80 and not re.search(r"[\.!\?:;]", clean):
            return True

        # Remove taxonomy/tag-like lines (comma-separated labels, no sentence punctuation).
        if clean.count(",") >= 2 and not re.search(r"[\.!\?:;]", clean):
            return True

        return False

    def _sanitize_line_text(text: str) -> str:
        """Remove promotional prefixes while keeping the main explanatory sentence."""
        clean = re.sub(r"\s+", " ", (text or "")).strip()
        if not clean:
            return ""

        norm = _normalize(clean)
        if ("tanitim" in norm or "sanal tur" in norm) and "hakkinda" in norm:
            clean = re.sub(r"(?is)^.*?\bhakk[ıi]nda\b\s*", "", clean).strip()

        return clean

    def _has_noisy_ancestor(element: Tag) -> bool:
        """Exclude content that lives inside news/event/card/announcement wrappers."""
        noisy_markers = re.compile(
            r"news|haber|duyuru|announcement|event|etkinlik|card|carousel|slider|related|quick|social|share|post|blog",
            re.IGNORECASE,
        )
        for parent in element.parents:
            if parent is None or not isinstance(parent, Tag):
                continue
            attrs = parent.attrs if isinstance(parent.attrs, dict) else {}
            parent_id = str(attrs.get("id", "") or "")
            parent_classes = attrs.get("class", [])
            if isinstance(parent_classes, str):
                parent_classes = [parent_classes]
            elif not isinstance(parent_classes, (list, tuple, set)):
                parent_classes = []
            blob = " ".join([parent_id, *[str(c) for c in parent_classes if c]])
            if noisy_markers.search(blob):
                return True
        return False

    working = BeautifulSoup(str(soup), "lxml")
    _clean_node(working)
    target = _pick_main_content(working)

    # Remove only short link-list blocks (avoid deleting real text sections).
    for candidate in target.find_all(["ul", "ol"]):
        text = candidate.get_text(" ", strip=True)
        if _is_short_link_list_block(candidate) and _is_noise_text_block(text):
            candidate.decompose()

    lines = []
    for element in target.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"]):
        if _has_noisy_ancestor(element):
            continue

        text = _sanitize_line_text(element.get_text(" ", strip=True))
        if not text:
            continue
        if len(text) < 3:
            continue
        if len(text) < 80 and _is_noise_text_block(text):
            continue
        if _is_noise_line(text):
            continue

        # Prevent storing link-menu labels as content.
        if element.name in {"li", "p"} and len(text) < 80:
            anchor_count = len(element.find_all("a", href=True))
            if anchor_count > 0 and anchor_count == len(element.find_all("a")):
                continue

        # Keep output as readable plain text paragraphs.
        lines.append(text)

    # Deduplicate consecutive identical lines and collapse whitespace noise.
    result = []
    prev = ""
    for line in lines:
        clean_line = re.sub(r"\s+", " ", line).strip()
        if clean_line and clean_line != prev:
            result.append(clean_line)
            prev = clean_line

    paragraphs = [line for line in result if len(line) >= 40]

    # Ensure at least 2-3 readable paragraphs if content exists.
    if len(paragraphs) < 2:
        fallback_sentences = []
        for sentence in re.split(r"(?<=[\.!\?])\s+", target.get_text(" ", strip=True)):
            sentence = _sanitize_line_text(re.sub(r"\s+", " ", sentence).strip())
            if not sentence or _is_noise_line(sentence):
                continue
            if len(sentence) >= 40:
                fallback_sentences.append(sentence)
            if len(fallback_sentences) >= 6:
                break
        if fallback_sentences:
            paragraphs = fallback_sentences

    return "\n\n".join(paragraphs)


def _extract_title(soup: BeautifulSoup) -> str:
    """Extract page title."""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
        # Clean up common suffixes
        for suffix in [" | Acıbadem Üniversitesi", " - Acıbadem", " | ACU"]:
            title = title.replace(suffix, "")
        return title.strip()

    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    return ""


def _is_department_page_url(url: str) -> bool:
    """Identify department/faculty pages that must not be dropped by low-content filters."""
    normalized = (url or "").lower()
    return any(token in normalized for token in [
        "bilgisayar-muhendisligi",
        "muhendislik",
        "bolumler",
    ])


def _fallback_body_text(soup: BeautifulSoup, max_chars: int = 4000) -> str:
    """Soft fallback: keep at least some readable body text if extraction gets too strict."""
    target = soup.find("main") or soup.find("article") or soup.body or soup
    text = target.get_text(" ", strip=True) if target else ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


class ACUScraper:
    """Scraper for the main ACU website (acibadem.edu.tr)."""

    def __init__(self):
        self.base_domain = "www.acibadem.edu.tr"
        self.delay = settings.SCRAPE_DELAY
        self.max_pages = settings.SCRAPE_MAX_PAGES
        self.visited = set()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ACU-Chatbot-Scraper/1.0 (Educational Project; +https://github.com/acu-chatbot)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
        })

    def _is_valid_url(self, url: str) -> bool:
        """Check if URL belongs to the ACU domain and should be scraped."""
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc != self.base_domain:
            return False
        if _should_skip_url(url):
            return False
        return True

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Extract valid links from a page."""
        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            full_url = urljoin(base_url, href)
            # Normalize URL
            parsed = urlparse(full_url)
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if normalized.endswith("/"):
                normalized = normalized[:-1]
            if normalized and self._is_valid_url(normalized) and normalized not in self.visited:
                links.append(normalized)
        return list(set(links))

    def scrape_page(self, url: str) -> Optional[dict]:
        """
        Scrape a single page.

        Returns:
            dict with keys: url, title, content, html, category, language
            or None if scraping failed
        """
        if url in self.visited:
            return None

        self.visited.add(url)

        try:
            logger.info(f"Scraping: {url}")
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"

            soup = BeautifulSoup(response.text, "lxml")

            title = _extract_title(soup)
            content = _extract_text_from_html(soup)
            is_department_page = _is_department_page_url(url)

            if not content or not content.strip():
                content = _fallback_body_text(soup)

            # For department pages, preserve title with a clean body.
            if re.search(r"/bolumler?/|muhendisligi|fakultesi", url, re.IGNORECASE) and title:
                normalized_content = content.strip().lower()
                normalized_title = title.strip().lower()
                if normalized_title not in normalized_content[:300]:
                    content = f"# {title}\n\n{content}".strip()

            # Low-content guard is intentionally soft now.
            # Department pages bypass low-content filtering completely.
            if not content or not content.strip():
                if title and is_department_page:
                    content = f"# {title}".strip()
                else:
                    logger.debug(f"Skipping empty-content page: {url}")
                    return None

            # If content is short but non-empty, keep it.
            if len(content.strip()) < 20 and not is_department_page:
                logger.debug(f"Skipping low-content page: {url}")
                return None

            return {
                "url": url,
                "title": title,
                "content": content,
                "html": response.text[:50000],  # Store first 50KB of HTML
                "category": _categorize_url(url),
                "language": "tr",
                "source": "main",
                "links": self._extract_links(soup, url),
            }

        except requests.RequestException as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return None

    def scrape_all(self, callback=None) -> list[dict]:
        """
        Crawl the ACU website starting from seed URLs.

        Args:
            callback: Optional function called with (page_data, current_count, total_urls)

        Returns:
            List of scraped page data dicts
        """
        to_visit = list(SEED_URLS)
        results = []

        while to_visit and len(results) < self.max_pages:
            url = to_visit.pop(0)

            if url in self.visited:
                continue

            page_data = self.scrape_page(url)
            if page_data:
                # Extract new links to visit
                new_links = page_data.pop("links", [])
                to_visit.extend(new_links)

                results.append(page_data)

                # Save to database
                _, created = WebPage.objects.update_or_create(
                    url=page_data["url"],
                    defaults={
                        "title": page_data["title"],
                        "content": page_data["content"],
                        "html": page_data["html"],
                        "source": page_data["source"],
                        "category": page_data["category"],
                        "language": page_data["language"],
                        "is_processed": False,
                    },
                )
                logger.debug(f"{'Created' if created else 'Updated'} WebPage: {page_data['url']}")

                if callback:
                    callback(page_data, len(results), len(to_visit))

            # Respect rate limiting
            time.sleep(self.delay)

        logger.info(f"Scraping complete. Total pages: {len(results)}")
        return results
