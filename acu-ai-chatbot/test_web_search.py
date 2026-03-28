import os, django, json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.services.web_search_service import web_search_service

print("=== Web Search Test ===")
results = web_search_service.search("mühendislik fakültesi bölümleri")
print(f"Result count: {len(results)}")
for i, r in enumerate(results):
    content_len = len(r.get("content", ""))
    snippet_len = len(r.get("snippet", ""))
    print(f"\n--- Result {i+1} ---")
    print(f"Title: {r['title']}")
    print(f"URL: {r['url']}")
    print(f"Snippet length: {snippet_len}")
    print(f"Content length: {content_len}")
    print(f"Content preview: {r.get('content', '')[:200]}...")

print("\n=== Web Context for LLM ===")
ctx = web_search_service.build_web_context(results)
print(f"Context total length: {len(ctx)}")
print(f"Context preview:\n{ctx[:500]}...")
