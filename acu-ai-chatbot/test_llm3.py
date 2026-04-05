import os
import sys
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.services.llm_service import LLMService

llm = LLMService()
gen = llm.generate_stream(
    "Mühendislik fakültesinde hangi bölümler var",
    "Mühendislik - Vikipedi. Mühendis Nedir, Ne İş Yapar? Mühendis Olmak İçin 2026 Mühendislik..."
)

print("--- YANIT BAŞLADI ---")
for chunk in gen:
    try:
        data = json.loads(chunk)
        print(data.get("content", ""), end="", flush=True)
    except Exception as e:
        print(repr(e))
print("\n--- YANIT BİTTİ ---")
