"""
Enhanced Resume-Capable Scraper for ACU.
Saves progress to JSON checkpoint — restarts from where it left off.
Each page is saved to DB immediately (no memory accumulation).
"""
import json
import logging
import os
import re
import time
from urllib.parse import urljoin, urlparse

import django
import requests
from bs4 import BeautifulSoup

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from chat.models import DocumentChunk, WebPage  # noqa: E402
from chat.services.rag_service import rag_service  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

CHECKPOINT_FILE = "/tmp/scrape_checkpoint.json"

# ── Massive expanded seed URLs ───────────────────────────────────────────────
SEED_URLS = [
    # Ana sayfa & hakkında
    "https://www.acibadem.edu.tr/",
    "https://www.acibadem.edu.tr/universite/hakkinda",
    "https://www.acibadem.edu.tr/universite/hakkinda/misyon-vizyon-temel-degerler",
    "https://www.acibadem.edu.tr/universite/hakkinda/neden-acu",
    "https://www.acibadem.edu.tr/universite/hakkinda/universite-yonetimi",
    "https://www.acibadem.edu.tr/universite/rektorluge-bagli-birimler",
    "https://www.acibadem.edu.tr/iletisim",
    # Programlar genel
    "https://www.acibadem.edu.tr/programlar",
    "https://www.acibadem.edu.tr/akademik",
    "https://www.acibadem.edu.tr/akademik/lisans",
    # Tıp Fakültesi
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi",
    "https://www.acibadem.edu.tr/tip-fakultesi",
    # Eczacılık
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/eczacilik-fakultesi",
    # Sağlık Bilimleri
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/hemsirelik",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/fizyoterapi-ve-rehabilitasyon",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/beslenme-ve-diyetetik",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/saglik-yonetimi",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/odyoloji",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/dil-ve-konusma-terapisi",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/ergoterapi",
    # Mühendislik ve Doğa Bilimleri (KRİTİK)
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bilgisayar-muhendisligi",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/biyomedikal-muhendisligi",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/yazilim-muhendisligi",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/endustri-muhendisligi",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/molekuler-biyoloji-ve-genetik",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/yapay-zeka-muhendisligi",
    # İnsan ve Toplum Bilimleri
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/insan-ve-toplum-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/psikoloji",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/sosyoloji",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/gastronomi-ve-mutfak-sanatlari",
    # Ön Lisans
    "https://www.acibadem.edu.tr/akademik/onlisans",
    "https://www.acibadem.edu.tr/akademik/onlisans/saglik-hizmetleri-meslek-yuksekokulu",
    "https://www.acibadem.edu.tr/akademik/onlisans/meslek-yuksekokulu",
    "https://www.acibadem.edu.tr/akademik/ortak-dersler-bolumleri",
    # Lisansüstü
    "https://www.acibadem.edu.tr/akademik/lisansustu",
    "https://www.acibadem.edu.tr/akademik/lisansustu/saglik-bilimleri-enstitusu",
    "https://www.acibadem.edu.tr/akademik/lisansustu/fen-bilimleri-enstitusu",
    "https://www.acibadem.edu.tr/akademik/lisansustu/sosyal-bilimler-enstitusu",
    "https://www.acibadem.edu.tr/akademik/lisansustu/senoloji-arastirma-enstitusu",
    # Aday & Ücretler (KRİTİK)
    "https://www.acibadem.edu.tr/aday/ogrenci",
    "https://www.acibadem.edu.tr/aday/ogrenci/lisans-on-lisans-programlari",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/lisans/lisans-ogrenim-ucretleri-2025-2026",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/lisans/lisans-kontenjan-ve-puan-tablosu",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari/basari-bursu",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari/destek-bursu",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari/sporcu-bursu",
    "https://www.acibadem.edu.tr/aday/ogrenci/yatay-gecis",
    "https://www.acibadem.edu.tr/aday/ogrenci/dikey-gecis",
    # Öğrenci
    "https://www.acibadem.edu.tr/ogrenci/ogrenci",
    "https://www.acibadem.edu.tr/ogrenci/ogrenci-isleri",
    "https://www.acibadem.edu.tr/ogrenci/ogrenci-isleri/akademik-takvim",
    "https://www.acibadem.edu.tr/ogrenci/ogrenci-isleri/cift-anadal-yandal-programlari",
    "https://www.acibadem.edu.tr/ogrenci/odeme-yontemleri",
    # Kampüs Yaşamı (KRİTİK)
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam",
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam/ogrenci-kulupleri",
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam/spor-merkezi",
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam/acibadem-mehmet-ali-aydinlar-universitesi-ogrenci-yurtlari/hakkinda",
    "https://www.acibadem.edu.tr/ogrenci/mezuniyet-projeleri-fuari/hakkinda",
    # Uluslararası & Kariyer
    "https://www.acibadem.edu.tr/global-degisim-programlari",
    "https://www.acibadem.edu.tr/uluslararasi-ofis",
    "https://www.acibadem.edu.tr/kariyer-merkezi",
    "https://www.acibadem.edu.tr/surdurulebilir-kampus",
    "https://www.acibadem.edu.tr/universite/merkezler-ve-kurullar/arastirma-merkezleri",
]

SKIP_PATTERNS = [
    r"\.pdf$", r"\.jpg$", r"\.png$", r"\.gif$", r"\.mp4$", r"\.zip$",
    r"javascript:", r"mailto:", r"tel:", r"#$", r"/en/",
    r"login", r"signin", r"auth",
]


def _should_skip(url: str) -> bool:
    for p in SKIP_PATTERNS:
        if re.search(p, url, re.IGNORECASE):
            return True
    return False


def _categorize_url(url: str) -> str:
    path = urlparse(url).path.lower()
    cats = {
        "department": [r"bolum", r"muhendislik", r"tip-fak", r"eczacilik", r"psikoloji", r"hemsirelik"],
        "admission": [r"aday", r"basvuru", r"ucret", r"burs", r"kontenjan", r"yatay-gecis", r"dikey-gecis"],
        "campus": [r"kampus", r"kutuphane", r"spor", r"kulup", r"yurt", r"yasam"],
        "academic": [r"akademik", r"ders", r"mufredat", r"program", r"lisans", r"lisansustu"],
        "student": [r"ogrenci", r"erasmus", r"staj", r"mezuniyet"],
        "research": [r"arastirma", r"yayin", r"proje"],
        "contact": [r"iletisim"],
        "about": [r"hakkinda", r"misyon", r"vizyon"],
    }
    for cat, patterns in cats.items():
        for p in patterns:
            if re.search(p, path):
                return cat
    return "general"


def _extract_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["script", "style", "iframe", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(["header", "footer"]):
        tag.decompose()

    noise = re.compile(r"cookie|popup|modal|navbar|breadcrumb", re.I)
    for div in soup.find_all(["div", "section", "nav"], class_=noise):
        div.decompose()

    main = soup.find("main") or soup.find(id=re.compile(r"main|content|body", re.I))
    target = main if main and len(main.get_text(strip=True)) > 200 else (soup.body or soup)

    lines, seen = [], set()
    for el in target.find_all(["h1","h2","h3","h4","h5","h6","p","li","td","th","strong"]):
        t = el.get_text(strip=True)
        if t and len(t) > 4 and t not in seen:
            seen.add(t)
            if el.name in ("h1","h2","h3"):
                prefix = "#" * int(el.name[1])
                lines.append(f"\n{prefix} {t}\n")
            elif el.name == "li":
                lines.append(f"• {t}")
            else:
                lines.append(t)

    result = "\n".join(lines)
    if len(result) < 100:
        full = target.get_text(separator="\n", strip=True)
        deduped, seen2 = [], set()
        for line in full.split("\n"):
            line = line.strip()
            if line and len(line) > 4 and line not in seen2:
                seen2.add(line)
                deduped.append(line)
        result = "\n".join(deduped)
    return result


def _extract_title(soup: BeautifulSoup) -> str:
    t = soup.find("title")
    if t:
        title = t.get_text(strip=True)
        for s in [" | Acıbadem Üniversitesi", " - Acıbadem", " | ACU"]:
            title = title.replace(s, "")
        return title.strip()
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE) as f:
                cp = json.load(f)
            logger.info(f"Loaded checkpoint: {len(cp['visited'])} visited, {len(cp['queue'])} in queue")
            return cp
        except Exception as e:
            logger.warning(f"Checkpoint corrupted, starting fresh: {e}")
    return {"visited": [], "queue": list(SEED_URLS), "saved_count": 0, "chunk_count": 0}


def save_checkpoint(visited: set, queue: list, saved: int, chunks: int):
    try:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump({
                "visited": list(visited),
                "queue": queue[:2000],  # Cap queue size
                "saved_count": saved,
                "chunk_count": chunks,
            }, f)
    except Exception as e:
        logger.warning(f"Failed to save checkpoint: {e}")


def save_page_to_db(page_data: dict) -> int:
    """Save one page to DB immediately and embed it. Returns chunk count."""
    try:
        webpage, created = WebPage.objects.get_or_create(
            url=page_data["url"],
            defaults={
                "title": page_data.get("title", ""),
                "content": page_data.get("content", ""),
                "html": page_data.get("html", "")[:50000],
                "category": page_data.get("category", "general"),
                "language": "tr",
                "source": "main",
            },
        )

        if not created:
            # Update existing page with fresh content
            webpage.title = page_data.get("title", webpage.title)
            webpage.content = page_data.get("content", webpage.content)
            webpage.html = page_data.get("html", webpage.html)[:50000]
            webpage.category = page_data.get("category", webpage.category)
            webpage.is_processed = False
            webpage.save()

        chunk_count = rag_service.process_webpage(webpage, force=True)
        return chunk_count
    except Exception as e:
        logger.error(f"DB save failed for {page_data.get('url')}: {e}")
        return 0


def scrape_with_resume(max_pages: int = 1200, delay: float = 1.5):
    """Main scraping function with full checkpoint/resume support."""
    cp = load_checkpoint()
    visited = set(cp["visited"])
    queue = cp["queue"]
    saved_count = cp["saved_count"]
    chunk_count = cp["chunk_count"]

    # Merge seed URLs into queue if not visited
    for url in SEED_URLS:
        if url not in visited and url not in queue:
            queue.insert(0, url)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ACU-Chatbot-Scraper/2.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "tr-TR,tr;q=0.9",
    })

    base_domain = "www.acibadem.edu.tr"
    logger.info(f"Starting scrape — {len(visited)} already visited, {len(queue)} in queue")

    while queue and saved_count < max_pages:
        url = queue.pop(0)

        if url in visited:
            continue

        # Validate URL
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc != base_domain:
            visited.add(url)
            continue
        if _should_skip(url):
            visited.add(url)
            continue

        visited.add(url)

        try:
            logger.info(f"[{saved_count+1}/{max_pages}] Scraping: {url}")
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"

            soup = BeautifulSoup(resp.text, "lxml")
            title = _extract_title(soup)
            content = _extract_text(soup)

            # Quality filter
            if len(content.strip()) < 200:
                logger.debug(f"  Skip (low content {len(content)} chars): {url}")
                time.sleep(delay * 0.3)
                continue

            # Boilerplate filter: if >60% of content is nav/menu items
            lines = [line for line in content.split("\n") if line.strip()]
            short_lines = [line for line in lines if len(line.strip()) < 25]
            if lines and len(short_lines) / len(lines) > 0.65 and len(content) < 1000:
                logger.debug(f"  Skip (boilerplate): {url}")
                continue

            page_data = {
                "url": url,
                "title": title,
                "content": content,
                "html": resp.text[:50000],
                "category": _categorize_url(url),
            }

            # Save immediately to DB
            chunks = save_page_to_db(page_data)
            saved_count += 1
            chunk_count += chunks
            logger.info(f"  ✓ Saved '{title[:60]}' → {chunks} chunks")

            # Extract and queue new links
            for a in soup.find_all("a", href=True):
                href = a["href"]
                full = urljoin(url, href)
                p = urlparse(full)
                normalized = f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")
                if (normalized
                        and p.netloc == base_domain
                        and not _should_skip(normalized)
                        and normalized not in visited
                        and normalized not in queue):
                    queue.append(normalized)

            # Save checkpoint every 10 pages
            if saved_count % 10 == 0:
                save_checkpoint(visited, queue, saved_count, chunk_count)
                logger.info(f"  📌 Checkpoint saved — {saved_count} pages, {chunk_count} chunks, {len(queue)} in queue")

        except requests.RequestException as e:
            logger.warning(f"  ✗ Failed: {url} — {e}")
        except Exception as e:
            logger.error(f"  ✗ Error: {url} — {e}")

        time.sleep(delay)

    # Final checkpoint
    save_checkpoint(visited, queue, saved_count, chunk_count)

    logger.info("=" * 60)
    logger.info("SCRAPE COMPLETE")
    logger.info(f"Pages saved: {saved_count}")
    logger.info(f"Chunks created: {chunk_count}")
    logger.info(f"Queue remaining: {len(queue)}")
    logger.info("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=1200)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--clear", action="store_true", help="Clear main site data first")
    args = parser.parse_args()

    if args.clear:
        logger.info("Clearing existing main site data...")
        from chat.models import WebPage, DocumentChunk
        main_pages = WebPage.objects.filter(source="main")
        DocumentChunk.objects.filter(web_page__in=main_pages).delete()
        main_pages.delete()
        # Also clear checkpoint
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
        logger.info("Cleared.")

    scrape_with_resume(max_pages=args.max_pages, delay=args.delay)
