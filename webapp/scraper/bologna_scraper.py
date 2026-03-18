"""
Bologna System Scraper — Scrapes academic data from obs.acibadem.edu.tr

Handles JavaScript-rendered pages using requests (with fallback strategies).
Collects: programs, courses, curricula, learning outcomes, ECTS credits.
"""

import logging
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)

# Bologna system base URLs
BOLOGNA_BASE = "https://obs.acibadem.edu.tr/oibs/bologna/"

# Known faculty/program pages (direct links to avoid complex JS navigation)
PROGRAM_URLS = [
    # Tıp Fakültesi
    {
        "url": "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=6",
        "name": "Tıp Fakültesi",
        "category": "faculty",
    },
    # Eczacılık Fakültesi
    {
        "url": "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=62",
        "name": "Eczacılık Fakültesi",
        "category": "faculty",
    },
    # Sağlık Bilimleri Fakültesi
    {
        "url": "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=63",
        "name": "Sağlık Bilimleri Fakültesi",
        "category": "faculty",
    },
    # Mühendislik ve Doğa Bilimleri Fakültesi
    {
        "url": "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=64",
        "name": "Mühendislik ve Doğa Bilimleri Fakültesi",
        "category": "faculty",
    },
    # Bilgisayar Mühendisliği
    {
        "url": "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=6246",
        "name": "Bilgisayar Mühendisliği",
        "category": "department",
    },
    # Fen-Edebiyat Fakültesi
    {
        "url": "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=65",
        "name": "Fen-Edebiyat Fakültesi",
        "category": "faculty",
    },
    # Sağlık Hizmetleri MYO
    {
        "url": "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=7",
        "name": "Sağlık Hizmetleri MYO",
        "category": "faculty",
    },
    # Lisansüstü Eğitim Enstitüsü
    {
        "url": "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=8",
        "name": "Lisansüstü Eğitim Enstitüsü",
        "category": "faculty",
    },
]


def _clean_bologna_text(soup: BeautifulSoup) -> str:
    """Extract and clean text from Bologna system pages."""
    # Remove scripts and styles
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    # Try to find the main content area
    content_div = (
        soup.find("div", id="contentArea")
        or soup.find("div", class_="content")
        or soup.find("div", id="MainContent")
        or soup.find("form")
    )

    target = content_div if content_div else soup

    lines = []

    # Extract table data (Bologna system uses lots of tables)
    for table in target.find_all("table"):
        headers = []
        for th in table.find_all("th"):
            headers.append(th.get_text(strip=True))
        if headers:
            lines.append(" | ".join(headers))
            lines.append("-" * 40)

        for row in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all(["td"])]
            if any(cells):
                lines.append(" | ".join(cells))

    # Also get non-table text
    for elem in target.find_all(["h1", "h2", "h3", "h4", "p", "li", "span"]):
        text = elem.get_text(strip=True)
        if text and len(text) > 3 and text not in "\n".join(lines):
            if elem.name in ("h1", "h2", "h3", "h4"):
                prefix = "#" * min(int(elem.name[1]), 4)
                lines.append(f"\n{prefix} {text}\n")
            elif elem.name == "li":
                lines.append(f"• {text}")
            else:
                lines.append(text)

    # Deduplicate
    result = []
    prev = ""
    for line in lines:
        if line.strip() and line != prev:
            result.append(line)
            prev = line

    return "\n".join(result)


class BolognaScraper:
    """Scraper for the ACU Bologna/OBS system."""

    def __init__(self):
        self.delay = settings.SCRAPE_DELAY
        self.visited = set()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ACU-Chatbot-Scraper/1.0 (Educational Project)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "tr-TR,tr;q=0.9",
        })

    def scrape_page(self, url: str, name: str = "", category: str = "academic") -> Optional[dict]:
        """Scrape a single Bologna system page."""
        if url in self.visited:
            return None

        self.visited.add(url)

        try:
            logger.info(f"Scraping Bologna: {name or url}")
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            response.encoding = "utf-8"

            soup = BeautifulSoup(response.text, "lxml")
            content = _clean_bologna_text(soup)

            if len(content.strip()) < 30:
                logger.debug(f"Skipping low-content Bologna page: {url}")
                return None

            # Extract title
            title = name
            if not title:
                title_tag = soup.find("title")
                if title_tag:
                    title = title_tag.get_text(strip=True)
                h1 = soup.find("h1")
                if h1:
                    title = h1.get_text(strip=True)

            # Extract links to subpages (course pages, curriculum, etc.)
            links = []
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "bologna" in href or "oibs" in href:
                    full_url = urljoin(url, href)
                    if full_url not in self.visited:
                        link_text = a_tag.get_text(strip=True)
                        links.append({"url": full_url, "text": link_text})

            return {
                "url": url,
                "title": title,
                "content": content,
                "html": response.text[:50000],
                "category": category,
                "language": "tr",
                "source": "bologna",
                "links": links,
            }

        except requests.RequestException as e:
            logger.warning(f"Failed to scrape Bologna page {url}: {e}")
            return None

    def scrape_all(self, callback=None) -> list[dict]:
        """
        Scrape all known Bologna program pages and their subpages.

        Returns:
            List of scraped page data dicts
        """
        results = []
        to_visit = [(p["url"], p["name"], p["category"]) for p in PROGRAM_URLS]

        while to_visit and len(results) < settings.SCRAPE_MAX_PAGES:
            url, name, category = to_visit.pop(0)

            if url in self.visited:
                continue

            page_data = self.scrape_page(url, name, category)
            if page_data:
                # Queue subpage links
                links = page_data.pop("links", [])
                for link in links[:20]:  # Limit sublinks per page
                    if link["url"] not in self.visited:
                        to_visit.append((link["url"], link.get("text", ""), "academic"))

                results.append(page_data)

                if callback:
                    callback(page_data, len(results), len(to_visit))

            time.sleep(self.delay)

        logger.info(f"Bologna scraping complete. Total pages: {len(results)}")
        return results
