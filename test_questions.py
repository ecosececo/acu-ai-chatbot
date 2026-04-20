#!/usr/bin/env python3
import urllib.request
import json
import sys
import time

BASE_URL = "http://localhost:8000/api/chat/"

QUESTIONS = [
    # GEN
    ("GEN-1", "Acıbadem Üniversitesi ne zaman kuruldu?"),
    ("GEN-2", "Üniversitenin resmi adı nedir?"),
    ("GEN-3", "Hangi vakfa bağlı?"),
    ("GEN-4", "Kaç fakülte var?"),
    ("GEN-5", "Kampüs nerede?"),
    # FAK
    ("FAK-1", "Tıp Fakültesi kaç yıllık?"),
    ("FAK-2", "Eczacılık Fakültesi var mı?"),
    ("FAK-3", "Sağlık Bilimleri Fakültesi hangi bölümleri içeriyor?"),
    ("FAK-4", "Mühendislik Fakültesi hangi bölümleri içeriyor?"),
    ("FAK-5", "İnsan ve Toplum Bilimleri Fakültesi'nde ne okunan?"),
    # BOL
    ("BOL-1", "Bilgisayar Mühendisliği bölümü var mı?"),
    ("BOL-2", "Biyomedikal Mühendisliği bölümü hangi fakülteye bağlı?"),
    ("BOL-3", "Hemşirelik bölümü kaç yıllık?"),
    ("BOL-4", "Fizyoterapi ve Rehabilitasyon bölümü var mı?"),
    ("BOL-5", "Bilgisayar Mühendisliği ders programı nedir?"),
    # MUF
    ("MUF-1", "Bilgisayar Mühendisliği bölüm başkanı kim?"),
    ("MUF-2", "Mühendislik Fakültesi dekanı kim?"),
    # BUR
    ("BUR-1", "Burs imkânları neler?"),
    ("BUR-2", "Burs başvurusu ne zaman yapılır?"),
    # ULU
    ("ULU-1", "Uluslararası öğrenciler nasıl başvurabilir?"),
    ("ULU-2", "Erasmus programı var mı?"),
    # KAL
    ("KAL-1", "Akreditasyon bilgisi nedir?"),
    # SOS
    ("SOS-1", "Öğrenci kulüpleri var mı?"),
    ("SOS-2", "Üniversitede spor tesisleri var mı?"),
    # LIS
    ("LIS-1", "Lisansüstü programlar neler?"),
    # KAR
    ("KAR-1", "Kariyer hizmetleri nasıl?"),
    # ZOR
    ("ZOR-1", "Hukuk fakültesi var mi?"),
    ("ZOR-2", "Yazilim Muhendisligi bolumu var mi?"),
    ("ZOR-3", "Devlet universitesi mi?"),
    ("ZOR-4", "Muhendislik Fakultesi dekani kim?"),
    ("ZOR-5", "Universite hangi ilcede?"),
]

def ask(question):
    data = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))

passed = 0
failed = []

for code, q in QUESTIONS:
    try:
        result = ask(q)
        answer = result.get("answer", "").strip()
        sources = [s.get("title", "") for s in result.get("sources", [])]
        print(f"[{code}] {answer[:120]}")
        print(f"       Sources: {sources}")
        passed += 1
    except Exception as e:
        print(f"[{code}] ERROR: {e}")
        failed.append(code)
    time.sleep(1)

print(f"\n=== {passed}/{len(QUESTIONS)} answered (errors: {failed}) ===")
