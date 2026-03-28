"""
Kritik eksik sayfaları doğrudan scrape edip DB'ye ekle.
Bölüm sayfaları, burs, ücret, Erasmus gibi çok sorulan konular.
"""
import os, sys, django, requests, time
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import logging
import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from chat.models import WebPage, DocumentChunk
from chat.services.rag_service import rag_service

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Kritik sayfalar — bunların DB'de olmadığını veya yetersiz olduğunu biliyoruz
CRITICAL_URLS = [
    # === BÖLÜMLER (Mühendislik) ===
    ("https://www.acibadem.edu.tr/bolum/bilgisayar-muhendisligi", "department"),
    ("https://www.acibadem.edu.tr/bolum/biyomedikal-muhendisligi", "department"),
    ("https://www.acibadem.edu.tr/bolum/yazilim-muhendisligi", "department"),
    ("https://www.acibadem.edu.tr/bolum/endustri-muhendisligi", "department"),
    ("https://www.acibadem.edu.tr/bolum/molekuler-biyoloji-ve-genetik", "department"),
    ("https://www.acibadem.edu.tr/bolum/yapay-zeka-muhendisligi", "department"),
    # === BÖLÜMLER (Sağlık Bilimleri) ===
    ("https://www.acibadem.edu.tr/bolum/hemsirelik", "department"),
    ("https://www.acibadem.edu.tr/bolum/fizyoterapi-ve-rehabilitasyon", "department"),
    ("https://www.acibadem.edu.tr/bolum/beslenme-ve-diyetetik", "department"),
    ("https://www.acibadem.edu.tr/bolum/saglik-yonetimi", "department"),
    ("https://www.acibadem.edu.tr/bolum/odyoloji", "department"),
    ("https://www.acibadem.edu.tr/bolum/dil-ve-konusma-terapisi", "department"),
    ("https://www.acibadem.edu.tr/bolum/ergoterapi", "department"),
    ("https://www.acibadem.edu.tr/bolum/psikoloji", "department"),
    ("https://www.acibadem.edu.tr/bolum/sosyoloji", "department"),
    ("https://www.acibadem.edu.tr/bolum/gastronomi-ve-mutfak-sanatlari", "department"),
    ("https://www.acibadem.edu.tr/bolum/eczacilik", "department"),
    # === BURS & ÜCRETLER (KRİTİK) ===
    ("https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari", "admission"),
    ("https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari/basari-bursu", "admission"),
    ("https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari/destek-bursu", "admission"),
    ("https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari/sporcu-bursu", "admission"),
    ("https://www.acibadem.edu.tr/aday/ogrenci/egitim/lisans/lisans-ogrenim-ucretleri-2025-2026", "admission"),
    ("https://www.acibadem.edu.tr/aday/ogrenci/egitim/lisans/lisans-kontenjan-ve-puan-tablosu", "admission"),
    ("https://www.acibadem.edu.tr/aday/ogrenci/yatay-gecis", "admission"),
    ("https://www.acibadem.edu.tr/aday/ogrenci/dikey-gecis", "admission"),
    # === ERASMUS & ULUSLARARASI ===
    ("https://www.acibadem.edu.tr/global-degisim-programlari", "student"),
    ("https://www.acibadem.edu.tr/uluslararasi-ofis", "student"),
    # === KAMPÜS ===
    ("https://www.acibadem.edu.tr/ogrenci/acuda-yasam/ogrenci-kulupleri", "campus"),
    ("https://www.acibadem.edu.tr/surdurulebilir-kampus", "campus"),
    ("https://www.acibadem.edu.tr/kariyer-merkezi", "campus"),
    # === FAKÜLTE ANA SAYFALARI ===
    ("https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi", "department"),
    ("https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi", "department"),
    ("https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/insan-ve-toplum-bilimleri-fakultesi", "department"),
    ("https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/eczacilik-fakultesi", "department"),
    ("https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi", "department"),
    # === LİSANSÜSTÜ ===
    ("https://www.acibadem.edu.tr/akademik/lisansustu/saglik-bilimleri-enstitusu", "academic"),
    ("https://www.acibadem.edu.tr/akademik/lisansustu/fen-bilimleri-enstitusu", "academic"),
    ("https://www.acibadem.edu.tr/akademik/lisansustu/sosyal-bilimler-enstitusu", "academic"),
]

def extract_title(soup):
    t = soup.find("title")
    if t:
        title = t.get_text(strip=True)
        for s in [" | Acıbadem Üniversitesi", " - Acıbadem", " | ACU"]:
            title = title.replace(s, "")
        return title.strip()
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""

def extract_text(soup):
    for tag in soup.find_all(["script","style","iframe","noscript"]):
        tag.decompose()
    for tag in soup.find_all(["header","footer"]):
        tag.decompose()

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
    return "\n".join(lines)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; ACU-Chatbot/2.0)",
    "Accept-Language": "tr-TR,tr;q=0.9",
})

saved = 0
failed = 0

for url, category in CRITICAL_URLS:
    try:
        logger.info(f"Fetching: {url}")
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"

        soup = BeautifulSoup(resp.text, "lxml")
        title = extract_title(soup)
        content = extract_text(soup)

        if len(content.strip()) < 100:
            logger.warning(f"  Çok kısa içerik ({len(content)} char), atlandı")
            failed += 1
            time.sleep(0.5)
            continue

        webpage, created = WebPage.objects.update_or_create(
            url=url,
            defaults={
                "title": title,
                "content": content,
                "html": resp.text[:50000],
                "category": category,
                "language": "tr",
                "source": "main",
                "is_processed": False,
            }
        )

        chunk_count = rag_service.process_webpage(webpage, force=True)
        saved += 1
        action = "Oluşturuldu" if created else "Güncellendi"
        logger.info(f"  ✓ [{action}] '{title[:60]}' → {chunk_count} chunk")

    except Exception as e:
        logger.warning(f"  ✗ HATA: {url} — {e}")
        failed += 1

    time.sleep(0.8)

print()
print("=" * 60)
print(f"KRİTİK SAYFA SCRAPE TAMAMLANDI")
print(f"Kaydedilen: {saved}")
print(f"Başarısız:  {failed}")
print("=" * 60)

# Son DB durumu
from django.db.models import Count
for s in WebPage.objects.values('source').annotate(c=Count('id')).order_by('source'):
    print(f"  {s['source']}: {s['c']} sayfa")
from chat.models import DocumentChunk
print(f"  Toplam chunk: {DocumentChunk.objects.count()}")
