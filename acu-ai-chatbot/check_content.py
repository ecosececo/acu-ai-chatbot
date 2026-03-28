import os, sys, django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.models import WebPage, DocumentChunk
from django.db.models import Q

# Mühendislik ile ilgili tüm chunk'lar
print("=== MÜHENDİSLİK İÇERİKLERİ ===")
chunks = DocumentChunk.objects.filter(
    Q(content__icontains="Bilgisayar Mühendisliği") |
    Q(content__icontains="Biyomedikal Mühendisliği") |
    Q(content__icontains="Yazılım Mühendisliği") |
    Q(content__icontains="Yapay Zeka Mühendisliği")
).select_related('web_page')[:10]
print(f"Toplam eşleşen chunk: {DocumentChunk.objects.filter(Q(content__icontains='Bilgisayar Mühendisliği') | Q(content__icontains='Biyomedikal')).count()}")
for c in chunks:
    print(f"\nSayfa: {c.web_page.title[:60]}")
    print(f"URL: {c.web_page.url[:80]}")
    print(f"İçerik: {c.content[:300]}")
    print("---")

print()
print("=== BURS İÇERİKLERİ ===")
chunks2 = DocumentChunk.objects.filter(
    Q(content__icontains="burs") | Q(content__icontains="indirim")
).select_related('web_page')[:5]
print(f"Burs chunk sayısı: {DocumentChunk.objects.filter(content__icontains='burs').count()}")
for c in chunks2:
    print(f"\nSayfa: {c.web_page.title[:60]}")
    print(f"İçerik: {c.content[:200]}")
    print("---")

print()
print("=== ERASMUS İÇERİKLERİ ===")
erasmus = DocumentChunk.objects.filter(content__icontains="erasmus").select_related('web_page')
print(f"Erasmus chunk sayısı: {erasmus.count()}")
for c in erasmus[:3]:
    print(f"\nSayfa: {c.web_page.title[:60]}")
    print(f"İçerik: {c.content[:200]}")
    print("---")
