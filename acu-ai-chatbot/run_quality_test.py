"""Türkçe kalite test betiği — Django'ya direkt bağlanır."""
import json, time, urllib.request, http.cookiejar

BASE = "http://localhost:8000"

QUESTIONS = [
    ("Genel Bilgi",           "Acıbadem Üniversitesi nerede bulunuyor?"),
    ("Akademik Programlar",   "Bilgisayar Mühendisliği müfredatı nasıl yapılandırılmış?"),
    ("Kabul Koşulları",       "Bilgisayar Mühendisliği programına nasıl başvurabilirim?"),
    ("Ders Detayları",        "CSE 322 Bulut Bilişim dersi ne kapsamaktadır?"),
    ("Fakülte Bilgisi",       "Hangi fakülteler ve bölümler mevcut?"),
    ("Kampüs Yaşamı",         "Hangi öğrenci kulüpleri ve aktiviteler var?"),
    ("Ücretler ve Burslar",   "Hangi burs imkânları mevcut?"),
    ("Uluslararası Öğrenci",  "İngilizce eğitim veren programlar var mı?"),
    ("Kütüphane ve Kaynaklar","Kütüphane hizmetlerine nasıl erişebilirim?"),
    ("Kapsam Dışı",           "Acıbadem Sağlık Grubu'nun güncel hisse senedi fiyatı nedir?"),
]

# Get CSRF token via session
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
opener.open(f"{BASE}/")
csrf = next((c.value for c in jar if c.name == "csrftoken"), "test")

results = []
for i, (category, question) in enumerate(QUESTIONS, 1):
    print(f"[{i}/10] {category}: {question[:55]}...")
    payload = json.dumps({"question": question, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/chat/",
        data=payload,
        headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
        method="POST",
    )
    t0 = time.time()
    try:
        with opener.open(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        elapsed = round(time.time() - t0, 1)
        answer = data.get("answer", "").strip()
        sources = data.get("sources", [])
        error = data.get("error", False)
        print(f"    → {elapsed}s | {'HATA' if error else 'OK'} | {len(answer)} karakter | {len(sources)} kaynak")
        if answer and not error:
            print(f"    Yanıt: {answer[:120]}...")
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        answer = f"[API HATASI: {e}]"
        sources = []
        error = True
        print(f"    → {elapsed}s | HATA: {e}")

    results.append({
        "no": i, "category": category, "question": question,
        "answer": answer, "sources": sources,
        "elapsed": elapsed, "error": error,
    })
    time.sleep(3)

with open("/tmp/test_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\nTamamlandı. /tmp/test_results.json")
