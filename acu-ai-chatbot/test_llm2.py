import os
import sys
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.services.llm_service import LLMService

llm = LLMService()
gen = llm.generate_stream(
    "Acıbadem Üniversitesi burs imkanları hakkında bilgi ver, çok kısa bir özet olsun.",
    "Acıbadem Üniversitesi öğrencilerine tam burs ve %50 başarı bursu vermektedir. Destek bursları 20 bin TL nakit aylıktan oluşmaktadır."
)

print("--- YANIT BAŞLADI ---")
for chunk in gen:
    print(repr(chunk), flush=True)
print("\n--- YANIT BİTTİ ---")
