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

# Important seed URLs to start with
SEED_URLS = [
    "https://www.acibadem.edu.tr/",
    "https://www.acibadem.edu.tr/hakkimizda",
    "https://www.acibadem.edu.tr/akademik",
    "https://www.acibadem.edu.tr/fakulteler",
    "https://www.acibadem.edu.tr/aday-ogrenci",
    "https://www.acibadem.edu.tr/kampus-yasami",
    "https://www.acibadem.edu.tr/iletisim",
    "https://www.acibadem.edu.tr/lisans-programlari",
    "https://www.acibadem.edu.tr/lisansustu-programlar",
    "https://www.acibadem.edu.tr/tip-fakultesi",
    "https://www.acibadem.edu.tr/eczacilik-fakultesi",
    "https://www.acibadem.edu.tr/saglik-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/muhendislik-ve-doga-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/fen-edebiyat-fakultesi",
    "https://www.acibadem.edu.tr/saglik-hizmetleri-meslek-yuksekokulu",
    "https://www.acibadem.edu.tr/bilgisayar-muhendisligi",
    "https://www.acibadem.edu.tr/yazilim-muhendisligi",
    "https://www.acibadem.edu.tr/biyomedikal-muhendisligi",
    "https://www.acibadem.edu.tr/endüstri-muhendisligi",
    "https://www.acibadem.edu.tr/ogrenci-isleri",
    "https://www.acibadem.edu.tr/burs-ve-indirimler",
    "https://www.acibadem.edu.tr/ucretler",
    "https://www.acibadem.edu.tr/yatay-gecis",
    "https://www.acibadem.edu.tr/dikey-gecis",
    "https://www.acibadem.edu.tr/erasmus",
    "https://www.acibadem.edu.tr/kutuphane",
    "https://www.acibadem.edu.tr/yemekhane",
    "https://www.acibadem.edu.tr/spor-tesisleri",
    "https://www.acibadem.edu.tr/ogrenci-kulupleri",
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
    # Remove unwanted elements
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
        tag.decompose()

    # Try to find main content area
    main_content = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"content|main|body", re.I))
        or soup.find("div", id=re.compile(r"content|main|body", re.I))
    )

    target = main_content if main_content else soup.body if soup.body else soup

    # Extract text with structure
    lines = []
    for element in target.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "span", "div"]):
        text = element.get_text(strip=True)
        if text and len(text) > 2:
            # Add markdown-like headers
            if element.name in ("h1", "h2", "h3"):
                prefix = "#" * int(element.name[1])
                lines.append(f"\n{prefix} {text}\n")
            elif element.name == "li":
                lines.append(f"• {text}")
            else:
                lines.append(text)

    # Deduplicate consecutive identical lines
    result = []
    prev = ""
    for line in lines:
        if line != prev:
            result.append(line)
            prev = line

    return "\n".join(result)


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
