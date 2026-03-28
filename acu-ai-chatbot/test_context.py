import os, sys, django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.services.rag_service import rag_service
from chat.services.llm_service import llm_service

TEST_QUERIES = [
    "Mühendislik fakültesinde hangi bölümler var",
    "Burs imkanları nelerdir",
    "Kampüste hangi öğrenci kulüpleri var",
]

for q in TEST_QUERIES:
    print(f"\n{'='*60}")
    print(f"SORU: {q}")
    print(f"{'='*60}")
    
    results = rag_service.search(q, top_k=8)
    print(f"RAG sonuç sayısı: {len(results)}")
    
    context, sources = rag_service.build_context(q)
    print(f"Context uzunluğu: {len(context)} char")
    print(f"Kaynak sayısı: {len(sources)}")
    print()
    print("LLM'e giden context (ilk 500 char):")
    print(context[:500])
    print()
    print("KAYNAKLAR:")
    for s in sources:
        print(f"  - {s['title'][:50]} (skor: {s['score']})")
