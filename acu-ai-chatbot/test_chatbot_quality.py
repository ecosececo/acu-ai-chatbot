# -*- coding: utf-8 -*-
"""
Chatbot kalite testi - soru sor, cevabi degerlendir.

Kullanım:
    python test_chatbot_quality.py                  # Tüm testler
    python test_chatbot_quality.py --category ucret # Sadece ücret soruları
    python test_chatbot_quality.py --verbose        # RAG kaynaklarını da göster

Gereksinim: docker-compose up -d && servisler hazır
"""

import argparse
import json
import sys
import time

import requests

BASE_URL = "http://localhost/api"

# ── Test soruları ve beklenen anahtar kelimeler ─────────
# "keywords": cevapta bu kelimelerden EN AZ BİRİ olmalı
# "must_not": cevapta KESİNLİKLE olmamalı (uydurma link vs.)

TEST_CASES = [
    # ── Ücret & Burs ────────────────────────────────────
    {
        "category": "ucret",
        "question": "Acıbadem Üniversitesi lisans öğrenim ücretleri ne kadar?",
        "keywords": ["ücret", "tl", "yıllık", "öğrenim", "harç"],
        "must_not": ["http://uydurma", "bilmiyorum", "hata"],
    },
    {
        "category": "ucret",
        "question": "Burs imkânları neler? Tam burs var mı?",
        "keywords": ["burs", "indirim", "başarı", "tam", "muafiyet"],
        "must_not": [],
    },
    {
        "category": "ucret",
        "question": "Tıp fakültesi harç ücreti ne kadar?",
        "keywords": ["tıp", "ücret", "tl"],
        "must_not": [],
    },

    # ── Fakülteler & Bölümler ────────────────────────────
    {
        "category": "fakulte",
        "question": "Hangi fakülteler var Acıbadem Üniversitesi'nde?",
        "keywords": ["fakülte", "sağlık", "mühendislik", "eczacılık", "tıp"],
        "must_not": [],
    },
    {
        "category": "fakulte",
        "question": "Bilgisayar Mühendisliği bölümü hakkında bilgi verir misin?",
        "keywords": ["bilgisayar", "mühendislik", "bölüm", "yazılım"],
        "must_not": [],
    },
    {
        "category": "fakulte",
        "question": "Yapay Zeka Mühendisliği bölümü var mı?",
        "keywords": ["yapay zeka", "mühendislik", "bölüm"],
        "must_not": [],
    },

    # ── Başvuru & Kayıt ──────────────────────────────────
    {
        "category": "basvuru",
        "question": "Yatay geçiş nasıl yapılır?",
        "keywords": ["yatay geçiş", "kontenjan", "başvuru", "not", "gpa"],
        "must_not": [],
    },
    {
        "category": "basvuru",
        "question": "Taban puanlar ne kadar?",
        "keywords": ["puan", "taban", "yks", "sıralama", "kontenjan"],
        "must_not": [],
    },

    # ── Kampüs & Öğrenci Hayatı ──────────────────────────
    {
        "category": "kampus",
        "question": "Kütüphane saatleri nedir?",
        "keywords": ["kütüphane", "saat", "çalışma", "kaynak"],
        "must_not": [],
    },
    {
        "category": "kampus",
        "question": "Öğrenci yurdu var mı?",
        "keywords": ["yurt", "barınma", "konaklama", "öğrenci"],
        "must_not": [],
    },

    # ── Erasmus & Staj ───────────────────────────────────
    {
        "category": "uluslararasi",
        "question": "Erasmus programına nasıl başvurabilirim?",
        "keywords": ["erasmus", "değişim", "başvuru", "yurtdışı", "anlaşma"],
        "must_not": [],
    },

    # ── Lisansüstü ───────────────────────────────────────
    {
        "category": "lisansustu",
        "question": "Yüksek lisans programları neler?",
        "keywords": ["yüksek lisans", "enstitü", "program", "tez"],
        "must_not": [],
    },

    # ── Uydurma soru (hallucination testi) ──────────────
    {
        "category": "hallucination",
        "question": "Acıbadem Üniversitesi'nde uzay mühendisliği bölümü var mı?",
        "keywords": ["bulunmamaktad", "mevcut de", "yok", "bilgim yok", "bulunamad", "yer almamakta", "yer alm", "rastlayamad", "mevcut olmad"],
        "must_not": ["uzay mühendisliği bölümü açılmıştır", "evet var"],
        "note": "Uydurma bilgi vermemeli, 'yok/bilmiyorum' demeli",
    },
    {
        "category": "hallucination",
        "question": "Rektörün adı nedir?",
        "keywords": ["rektör", "üniversite", "yönetim"],
        "must_not": [],
        "note": "İsim uydurmamalı; bağlamda yoksa belirtmeli",
    },
]


def ask(question: str, verbose: bool = False) -> dict:
    try:
        resp = requests.post(
            f"{BASE_URL}/chat/",
            json={"question": question},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        print("\n[HATA] Servise bağlanılamadı. docker-compose up -d çalışıyor mu?")
        sys.exit(1)
    except Exception as e:
        return {"answer": f"[İSTEK HATASI: {e}]", "sources": []}


def evaluate(case: dict, result: dict, verbose: bool) -> bool:
    answer = result.get("answer", "").lower()
    sources = result.get("sources", [])

    keyword_hit = any(kw.lower() in answer for kw in case["keywords"])
    bad_hit = any(bad.lower() in answer for bad in case.get("must_not", []))

    passed = keyword_hit and not bad_hit

    status = "[GECTI]" if passed else "[KALDI]"
    print(f"  {status}")

    if not keyword_hit:
        print(f"    >> Beklenen kelimelerden hicbiri yok: {case['keywords']}")
    if bad_hit:
        hits = [b for b in case["must_not"] if b.lower() in answer]
        print(f"    >> Olmamasi gereken ifade bulundu: {hits}")

    if verbose:
        print(f"    Cevap: {result.get('answer', '')[:300]}...")
        if sources:
            print(f"    Kaynaklar: {[s.get('url','') for s in sources[:3]]}")

    return passed


def run_tests(category_filter: str = None, verbose: bool = False):
    cases = TEST_CASES
    if category_filter:
        cases = [c for c in TEST_CASES if c["category"] == category_filter]

    if not cases:
        print(f"Kategori bulunamadı: {category_filter}")
        print(f"Mevcut kategoriler: {sorted(set(c['category'] for c in TEST_CASES))}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  ACU Chatbot Kalite Testi — {len(cases)} soru")
    print(f"{'='*60}\n")

    passed = 0
    failed = 0
    results = []

    for i, case in enumerate(cases, 1):
        cat_label = f"[{case['category'].upper()}]"
        print(f"{i}/{len(cases)} {cat_label} {case['question']}")

        if case.get("note"):
            print(f"  Not: {case['note']}")

        start = time.time()
        result = ask(case["question"], verbose)
        elapsed = time.time() - start

        print(f"  Süre: {elapsed:.1f}s")

        ok = evaluate(case, result, verbose)
        results.append({**case, "passed": ok, "elapsed": elapsed, "answer": result.get("answer", "")})

        if ok:
            passed += 1
        else:
            failed += 1

        print()

    # ── Özet ────────────────────────────────────────────
    print(f"{'='*60}")
    print(f"  SONUÇ: {passed}/{len(cases)} geçti  ({failed} kaldı)")
    print(f"  Ortalama yanıt süresi: {sum(r['elapsed'] for r in results)/len(results):.1f}s")
    print(f"{'='*60}")

    if failed:
        print("\n  Başarısız sorular:")
        for r in results:
            if not r["passed"]:
                print(f"    - [{r['category']}] {r['question']}")
                print(f"      Cevap önizleme: {r['answer'][:150]}...")
    print()

    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", help="Sadece bu kategoriyi test et")
    parser.add_argument("--verbose", action="store_true", help="Tam cevapları göster")
    args = parser.parse_args()

    success = run_tests(args.category, args.verbose)
    sys.exit(0 if success else 1)
