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
from django.conf import settings

logger = logging.getLogger(__name__)

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

# Important seed URLs to start with (verified working URLs as of 2026-03)
SEED_URLS = [
    # ── Ana Sayfa & Genel ──
    "https://www.acibadem.edu.tr/",
    "https://www.acibadem.edu.tr/universite",
    "https://www.acibadem.edu.tr/universite/hakkinda",
    "https://www.acibadem.edu.tr/universite/hakkinda/misyon-vizyon-temel-degerler",
    "https://www.acibadem.edu.tr/universite/hakkinda/neden-acu",
    "https://www.acibadem.edu.tr/universite/hakkinda/universite-yonetimi",
    "https://www.acibadem.edu.tr/universite/rektorluge-bagli-birimler",
    "https://www.acibadem.edu.tr/universite/merkezler-ve-kurullar/arastirma-merkezleri",
    "https://www.acibadem.edu.tr/iletisim",
    # ── Programlar & Fakülteler ──
    "https://www.acibadem.edu.tr/programlar",
    "https://www.acibadem.edu.tr/akademik",
    "https://www.acibadem.edu.tr/akademik/lisans",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/eczacilik-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/insan-ve-toplum-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/onlisans",
    "https://www.acibadem.edu.tr/akademik/onlisans/saglik-hizmetleri-meslek-yuksekokulu",
    "https://www.acibadem.edu.tr/akademik/onlisans/meslek-yuksekokulu",
    "https://www.acibadem.edu.tr/akademik/ortak-dersler-bolumleri",
    # ── Lisansüstü ──
    "https://www.acibadem.edu.tr/akademik/lisansustu",
    "https://www.acibadem.edu.tr/akademik/lisansustu/saglik-bilimleri-enstitusu",
    "https://www.acibadem.edu.tr/akademik/lisansustu/fen-bilimleri-enstitusu",
    "https://www.acibadem.edu.tr/akademik/lisansustu/sosyal-bilimler-enstitusu",
    "https://www.acibadem.edu.tr/akademik/lisansustu/senoloji-arastirma-enstitusu",
    # ── Aday Öğrenci & Ücretler ──
    "https://www.acibadem.edu.tr/aday/ogrenci",
    "https://www.acibadem.edu.tr/aday/ogrenci/lisans-on-lisans-programlari",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/lisans/lisans-ogrenim-ucretleri-2025-2026",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/lisans/lisans-kontenjan-ve-puan-tablosu",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari",
    # ── Öğrenci ──
    "https://www.acibadem.edu.tr/ogrenci/ogrenci",
    "https://www.acibadem.edu.tr/ogrenci/ogrenci-isleri",
    "https://www.acibadem.edu.tr/ogrenci/ogrenci-isleri/akademik-takvim",
    "https://www.acibadem.edu.tr/ogrenci/ogrenci-isleri/cift-anadal-yandal-programlari",
    "https://www.acibadem.edu.tr/ogrenci/odeme-yontemleri",
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam",
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam/ogrenci-kulupleri",
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam/spor-merkezi",
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam/acibadem-mehmet-ali-aydinlar-universitesi-ogrenci-yurtlari/hakkinda",
    "https://www.acibadem.edu.tr/ogrenci/mezuniyet-projeleri-fuari/hakkinda",
    # ── Uluslararası & Kariyer ──
    "https://www.acibadem.edu.tr/global-degisim-programlari",
    "https://www.acibadem.edu.tr/uluslararasi-ofis",
    "https://www.acibadem.edu.tr/kariyer-merkezi",
    "https://www.acibadem.edu.tr/surdurulebilir-kampus",
    # ── Tıp Fakültesi (ayrı sayfa) ──
    "https://www.acibadem.edu.tr/tip-fakultesi",
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
    """Extract clean text content from parsed HTML.

    ACU website notes:
    - Main content is often inside <form> tags — do NOT remove <form>.
    - Program listings use <nav> elements — do NOT remove all <nav>.
    - <main> is often empty — always validate and fall back to <body>.
    """
    # Remove non-content elements
    for tag in soup.find_all(["script", "style", "iframe", "noscript"]):
        tag.decompose()

    # Remove header and footer (navigation menus, site chrome)
    for tag in soup.find_all(["header", "footer"]):
        tag.decompose()

    # Remove cookie/popup overlays and known nav-class patterns
    noise_patterns = re.compile(r"cookie|popup|modal|advertisement|navbar|nav-menu|site-header|site-footer|breadcrumb", re.I)
    for div in soup.find_all(["div", "section", "nav"], class_=noise_patterns):
        div.decompose()
    for div in soup.find_all(["div", "section", "nav"], id=noise_patterns):
        div.decompose()

    # Try to isolate main content area; fall back to full body
    main = soup.find("main") or soup.find(id=re.compile(r"main|content|body", re.I))
    target = main if main and len(main.get_text(strip=True)) > 200 else (soup.body if soup.body else soup)

    # Pass 1: Try structured extraction (headers, paragraphs, lists, tables)
    lines = []
    seen = set()
    for element in target.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "a", "span", "strong"]
    ):
        text = element.get_text(strip=True)
        # Short text (prices, numbers, short labels) is never deduplicated
        # Long text (paragraphs) is deduplicated to avoid repetition
        is_short = len(text) <= 30
        if text and len(text) > 3 and (is_short or text not in seen):
            if not is_short:
                seen.add(text)
            # Add markdown-like headers
            if element.name in ("h1", "h2", "h3"):
                prefix = "#" * int(element.name[1])
                lines.append(f"\n{prefix} {text}\n")
            elif element.name == "li":
                lines.append(f"• {text}")
            else:
                lines.append(text)

    result = "\n".join(lines)

    # Pass 2: If structured extraction yields too little, use full text
    if len(result) < 100:
        full_text = target.get_text(separator="\n", strip=True)
        # Deduplicate lines
        deduped = []
        seen_lines = set()
        for line in full_text.split("\n"):
            line = line.strip()
            if line and len(line) > 3 and line not in seen_lines:
                seen_lines.add(line)
                deduped.append(line)
        result = "\n".join(deduped)

    return result


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

            # Skip pages with very little content
            if len(content.strip()) < 50:
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

                if callback:
                    callback(page_data, len(results), len(to_visit))

            # Respect rate limiting
            time.sleep(self.delay)

        logger.info(f"Scraping complete. Total pages: {len(results)}")
        return results
