import os, sys, django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.models import WebPage, DocumentChunk
from django.db.models import Count, Avg

print("=" * 60)
print("DETAYLI VERITABANI ANALIZI")
print("=" * 60)

# Kaynak bazında
for s in WebPage.objects.values('source').annotate(count=Count('id')).order_by('source'):
    print(f"\nKaynak: {s['source']} — {s['count']} sayfa")

print()

# Kategori bazında main
print("MAIN SITE KATEGORİLERİ:")
for c in WebPage.objects.filter(source='main').values('category').annotate(count=Count('id')).order_by('-count'):
    print(f"  {c['category']:20s}: {c['count']}")

print()
print("ÖRNEK MAIN SAYFALARI (son 20):")
for p in WebPage.objects.filter(source='main').order_by('-id')[:20]:
    chunks = p.chunks.count()
    print(f"  [{chunks} chunk] {p.title[:60]} — {p.url[-60:]}")

print()

# Bologna örnek
print("ÖRNEK BOLOGNA SAYFALARI (son 10):")
for p in WebPage.objects.filter(source='bologna').order_by('-id')[:10]:
    chunks = p.chunks.count()
    print(f"  [{chunks} chunk] {p.title[:70]}")

print()
print(f"TOPLAM CHUNK: {DocumentChunk.objects.count()}")
print(f"EMBEDDİNG VAR: {DocumentChunk.objects.filter(embedding__isnull=False).count()}")
print("=" * 60)
