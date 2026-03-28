import os, sys, django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.services.rag_service import rag_service

TEST_QUERIES = [
    "Mühendislik fakültesinde hangi bölümler var",
    "Bilgisayar mühendisliği bölümü ders programı",
    "Tıp fakültesi kontenjan ve puan tablosu",
    "Burs imkanları nelerdir",
    "Erasmus programı nasıl başvurulur",
    "Kampüste hangi öğrenci kulüpleri var",
]

print("=" * 60)
print("RAG QUALITY TEST")
print("=" * 60)

for q in TEST_QUERIES:
    results = rag_service.search(q, top_k=3)
    print(f"\nSoru: {q}")
    print(f"Sonuç sayısı: {len(results)}")
    if results:
        best = results[0]
        print(f"En iyi skor: {best['score']:.4f}")
        print(f"Kaynak: {best['title'][:60]}")
        print(f"İçerik (ilk 200 char): {best['content'][:200]}")
    else:
        print("HİÇ SONUÇ YOK!")
    print("-" * 40)
