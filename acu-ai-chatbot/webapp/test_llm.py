import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.services.llm_service import web_llm_service  # noqa: E402

print("--- Test Basladi ---")
try:
    generator = web_llm_service.ask(
        question="Burs imkanlari ve ucretler hakkinda bilgi verir misin?",
        context="Acibadem Universitesi, farkli oranlarda (tam burs, %50, %25) basari burslari sunmaktadir. Ingilizce Tip programi yillik ucreti 500.000 TL civarindadir. Destek ve sporcu bursu da bulunmaktadir.",
        history=[]
    )
    for chunk in generator:
        print(chunk, end="", flush=True)
    print("\n--- Test Bitti ---")
except Exception as e:
    print(f"Hata: {e}")
