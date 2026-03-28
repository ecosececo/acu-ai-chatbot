import os, sys, django, requests
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from bs4 import BeautifulSoup

FACULTY_PAGES = [
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/insan-ve-toplum-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/lisans/lisans-ogrenim-ucretleri-2025-2026",
]

headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "tr-TR"}

for page_url in FACULTY_PAGES:
    print(f"\n{'='*60}")
    print(f"URL: {page_url}")
    print(f"{'='*60}")
    r = requests.get(page_url, timeout=15, headers=headers)
    print(f"Status: {r.status_code}")
    soup = BeautifulSoup(r.text, "lxml")
    print(f"Title: {soup.title.get_text(strip=True) if soup.title else 'N/A'}")
    
    # Find internal links
    links = []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        t = a.get_text(strip=True)
        if t and len(t) > 2 and ("acibadem.edu.tr" in h or h.startswith("/")):
            full = h if h.startswith("http") else f"https://www.acibadem.edu.tr{h}"
            if "acibadem.edu.tr" in full and full not in links:
                links.append((t[:40], full[:90]))
    
    for t, l in links[:20]:
        print(f"  {t:40s} -> {l}")
