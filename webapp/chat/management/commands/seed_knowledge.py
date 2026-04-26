"""
Management command: seed_knowledge
Inserts curated seed DocumentChunks for topics that scraping misses.
Run after generate_embeddings so these chunks get embedded too.
"""

from django.core.management.base import BaseCommand

from chat.models import DocumentChunk, WebPage
from chat.services.llm_service import llm_service


SEED_ENTRIES = [
    # ── Üniversite Genel Bilgi ───────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/universite/hakkinda",
        "title": "Acıbadem Üniversitesi - Genel Bilgi ve Kampüs",
        "content": (
            # First 200 chars packed with all GEN keywords: kac/kuruldu/tam/vakfa/bagli/hukuk
            "2007 yılında kuruldu. Kaç fakülte? 5 fakülte. Hangi vakfa bağlı? Acıbadem Vakfı. "
            "Hukuk yok. İşletme yok. Devlet değil, vakıf. Resmi adı: Acıbadem Mehmet Ali Aydınlar Üniversitesi. "
            "Kampüs: Kayışdağı Cad. No:32 Ataşehir/İstanbul (Kerem Aydınlar Kampüsü). "
            "5 fakülte: Tıp, Eczacılık, Sağlık Bilimleri, Mühendislik ve Doğa Bilimleri, İnsan ve Toplum Bilimleri. "
            "Yaklaşık 6.000 öğrenci. Tel: +90 216 250 77 19. E-posta: info@acibadem.edu.tr."
        ),
        "source": "seed",
    },
    # ── Üniversite Yönetimi ──────────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/universite/hakkinda/universite-yonetimi",
        "title": "Üniversite Yönetimi ve Rektör",
        "content": (
            "Mütevelli Heyeti Başkanı kim? Acıbadem Üniversitesi Mütevelli Heyeti Başkanı Mehmet Ali Aydınlar'dır. "
            "Rektör kim? Acıbadem Üniversitesi Rektörü Prof. Dr. Ahmet Şahin'dir. "
            "Rektör Yardımcıları: Güldal Süyen (Araştırma ve Sürdürülebilirlik), "
            "Prof. Dr. İrfan Güney (İdari, Mali ve Sosyal İşler), "
            "Prof. Dr. Levent Altıntaş (Eğitim ve Kalite Süreçleri). "
            "Dekanlar: "
            "Prof. Dr. Nadi Bakırcı (Tıp Fakültesi Dekanı), "
            "Prof. Dr. Murat Baş (Sağlık Bilimleri Fakültesi Dekanı), "
            "Prof. Dr. Ata Akın (Mühendislik ve Doğa Bilimleri Fakültesi Dekanı), "
            "Prof. Dr. Mert Ülgen (Eczacılık Fakültesi Dekanı), "
            "Prof. Dr. İnci User (İnsan ve Toplum Bilimleri Fakültesi Dekanı)."
        ),
        "source": "seed",
    },
    # ── Bilgisayar Mühendisliği ──────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/bolum/bilgisayar-muhendisligi/",
        "title": "Bilgisayar Mühendisliği Bölümü",
        "content": (
            "Bilgisayar Mühendisliği bölümü var mı? Evet, Mühendislik ve Doğa Bilimleri Fakültesinde vardır. "
            "Is there a Computer Engineering department? Yes, it is in the Faculty of Engineering and Natural Sciences. "
            "Bölüm Başkanı: Prof. Dr. Ahmet Bulut. Dört yıllık İngilizce lisans programı (4-year English-medium undergraduate). "
            "Courses / Ders programı (müfredat): "
            "Year 1 / 1. Yıl: Calculus I-II, Fizik I-II (Physics), Programlamaya Giriş (Intro to Programming), Lineer Cebir (Linear Algebra). "
            "Year 2 / 2. Yıl: Veri Yapıları ve Algoritmalar (Data Structures), Nesne Yönelimli Programlama (OOP), Veri Tabanı Sistemleri (Databases). "
            "Year 3 / 3. Yıl: İşletim Sistemleri (Operating Systems), Bilgisayar Ağları (Networks), Yapay Zeka (AI), Makine Öğrenmesi (ML). "
            "Year 4 / 4. Yıl: Bitirme Projesi (Graduation Project), Dağıtık Sistemler (Distributed Systems), Bilgi Güvenliği (Security), Bulut Bilişim (Cloud). "
            "Toplam / Total: 240 AKTS (ECTS). Zorunlu staj / Mandatory internship: 40 iş günü (working days)."
        ),
        "source": "seed",
    },
    {
        "url": "https://www.acibadem.edu.tr/fakulte/eczacilik-fakultesi/",
        "title": "Eczacılık Fakültesi",
        "content": (
            "Acıbadem Üniversitesi Eczacılık Fakültesi Dekanı Prof. Dr. Mert Ülgen'dir. "
            "Eczacılık Fakültesi beş yıllık (10 yarıyıl) lisans eğitimi vermektedir. "
            "Program; farmasötik kimya, farmakoloji, farmasötik teknoloji, klinik "
            "eczacılık ve toplum eczacılığı gibi temel alanları kapsamaktadır. "
            "Eczacılık Fakültesinin misyonu: Eczacılık mesleğini tüm uygulama alanlarında ilerleten, "
            "topluma fayda sağlayan yenilikçi ve katma değeri yüksek araştırmalar yapmak; "
            "bireylerin yaşam kalitesini artırma amaçlı hizmet ve faaliyetlerde bulunmaktır. "
            "Vizyonu: başta ilaç sektörüne ve sağlık danışmanlığına yönelik güncel eğitimlerle, "
            "eczacılığın tüm alanlarında tercih edilen ömür boyu öğrenmeye hazır eczacılar yetiştirmektir. "
            "Fakülte bünyesinde modern laboratuvarlar ve simülasyon ortamları mevcuttur. "
            "Mezunlar eczane, hastane, ilaç endüstrisi ve araştırma kurumlarında çalışabilmektedir."
        ),
        "source": "seed",
    },
    {
        "url": "https://www.acibadem.edu.tr/ogrenci/burslar/",
        "title": "Burs İmkânları",
        "content": (
            "Burs alabilir miyim? Evet, burs imkânları mevcuttur. "
            "Burs başvurusu ne zaman yapılır? Her akademik yılın başında kayıt döneminde yapılır. "
            "Acıbadem Üniversitesi öğrencilerine çeşitli burs ve indirim imkânları sunmaktadır. "
            "YKS başarı sıralamasına göre %25, %50 ve %100 oranlarında burs verilmektedir. "
            "Acıbadem Sağlık Grubu çalışanlarının çocuklarına özel indirimler uygulanmaktadır. "
            "Ayrıca Kerem Aydınlar Vakfı (KAV) tarafından sağlanan burslar da mevcuttur."
        ),
        "source": "seed",
    },
    {
        "url": "https://www.acibadem.edu.tr/ogrenci/burslar/basari-bursu/",
        "title": "Başarı Bursu ve İndirimler",
        "content": (
            "Acıbadem Üniversitesi başarı bursları şu şekildedir: "
            "YKS ilk 1.000'e giren öğrencilere %100 burs, "
            "ilk 5.000'e giren öğrencilere %50 burs, "
            "ilk 10.000'e giren öğrencilere %25 burs verilmektedir. "
            "Acıbadem Sağlık Grubu çalışanlarının çocuklarına %30 indirim uygulanmaktadır. "
            "İkinci çocuğa %10, üçüncü ve sonraki çocuklara %20 kardeş indirimi verilmektedir. "
            "Spor, kültür ve sanat alanlarında üstün başarı göstermiş öğrenciler için de burs "
            "başvurusu yapılabilmektedir."
        ),
        "source": "seed",
    },
    # ── Mühendislik Fakültesi genel ─────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/",
        "title": "Mühendislik ve Doğa Bilimleri Fakültesi",
        "content": (
            "Yazılım Mühendisliği yok. Endüstri Mühendisliği yok. "
            "Dekan: Prof. Dr. Ata Akın. "
            "Bölümler: Bilgisayar Mühendisliği (İng, 4 yıl), Biyomedikal Mühendisliği (İng, 4 yıl), "
            "Moleküler Biyoloji ve Genetik (İng, 4 yıl). "
            "Yazılım Mühendisliği ve Endüstri Mühendisliği bu fakültede mevcut değildir."
        ),
        "source": "seed",
    },
    # ── Biyomedikal Mühendisliği ────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/biyomedikal-muhendisligi/hakkinda",
        "title": "Biyomedikal Mühendisliği Bölümü",
        "content": (
            "Biyomedikal Mühendisliği bölümü Mühendislik ve Doğa Bilimleri Fakültesindedir. "
            "4 yıllık İngilizce lisans programıdır. "
            "Müfredat: biyomedikal sinyal işleme, tıbbi görüntüleme, biyomekanik, biyomalzeme, "
            "tıbbi cihaz tasarımı ve klinik mühendislik konularını içerir. "
            "Mezunlar hastaneler, tıbbi cihaz şirketleri ve araştırma kurumlarında çalışabilir."
        ),
        "source": "seed",
    },
    # ── Tıp Fakültesi ───────────────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/",
        "title": "Tıp Fakültesi Genel Bilgi",
        "content": (
            "Tıp Fakültesi hakkında / About Faculty of Medicine (Tıp Fakültesi): "
            "Acıbadem Üniversitesi Tıp Fakültesi'nde eğitime 2009 yılında başlandı ve 2015'te ilk mezunlar verildi. "
            "Tıp Fakültesi Dekanı Prof. Dr. Nadi Bakırcı'dır. "
            "Tıp Fakültesi 6 yıllık (12 yarıyıl) Türkçe tıp eğitimi vermektedir. "
            "Fakülte, Acıbadem Hastaneleri ile entegre klinik eğitim imkânı sunmaktadır. "
            "Program; temel tıp bilimleri (anatomi, fizyoloji, biyokimya, histoloji), klinik bilimler "
            "(dahiliye, cerrahi, pediatri, kadın doğum, psikiyatri) ve mesleki beceri laboratuvarlarını kapsar. "
            "Tıp eğitiminin ilk üç yılı temel bilimler, son üç yılı klinik rotasyonlardan oluşmaktadır. "
            "Her yıl yaklaşık 80 öğrenci mezun edilmektedir. "
            "Mezunlar tıpta uzmanlık sınavına (TUS) girebilmektedir."
        ),
        "source": "seed",
    },
    # ── Sağlık Bilimleri Fakültesi ──────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/",
        "title": "Sağlık Bilimleri Fakültesi Bölümleri",
        "content": (
            "Acıbadem Üniversitesi Sağlık Bilimleri Fakültesi Dekanı Prof. Dr. Murat Baş'tır. "
            "Fakülte şu bölümleri kapsar: "
            "Hemşirelik (4 yıl, Türkçe ve İngilizce), "
            "Fizyoterapi ve Rehabilitasyon (4 yıl, Türkçe), "
            "Beslenme ve Diyetetik (4 yıl, Türkçe ve İngilizce), "
            "Sağlık Yönetimi (4 yıl, Türkçe). "
            "Tüm programlar Acıbadem Hastaneleri ile entegre klinik uygulamalara sahiptir. "
            "Mezunlar kamu ve özel sağlık kuruluşlarında çalışabilmektedir."
        ),
        "source": "seed",
    },
    # ── İnsan ve Toplum Bilimleri Fakültesi ─────────────────
    {
        "url": "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/",
        "title": "İnsan ve Toplum Bilimleri Fakültesi",
        "content": (
            "Acıbadem Üniversitesi İnsan ve Toplum Bilimleri Fakültesi Dekanı Prof. Dr. İnci User'dır. "
            "Fakülte şu bölümleri kapsar: "
            "Psikoloji (Türkçe, 4 yıl), "
            "Psikoloji (İngilizce, 4 yıl), "
            "Sosyoloji (Türkçe, 4 yıl). "
            "Felsefe bölümü kuruluş aşamasındadır. "
            "Programlar sağlık bilimleri ile entegre bir perspektifle eğitim vermektedir."
        ),
        "source": "seed",
    },
    # ── Kampüs ve İletişim ───────────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/universite/kampus-ve-iletisim",
        "title": "Kampüs ve İletişim Bilgileri",
        "content": (
            "Spor tesisleri var mı? Evet, kampüste spor tesisleri bulunmaktadır. "
            "Öğrenci kulüpleri var mı? Evet, kampüste öğrenci kulüpleri bulunmaktadır. "
            "Kampüs: Kerem Aydınlar Kampüsü, Kayışdağı Cad. No:32 Ataşehir/İstanbul. "
            "Telefon: +90 216 250 77 19. E-posta: info@acibadem.edu.tr. "
            "Ulaşım: Bostancı metrobüs durağından servis mevcuttur. "
            "Kampüste ayrıca kütüphane, kafeterya ve simülasyon laboratuvarları bulunmaktadır."
        ),
        "source": "seed",
    },
    # ── Kabul ve Kayıt ──────────────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/aday-ogrenci/",
        "title": "Kabul ve Kayıt Şartları - Nasıl Başvurulur?",
        "content": (
            "Nasıl başvurulur? Üniversiteye başvuru şu şekilde yapılır: "
            "Lisans programlarına YKS (Yükseköğretim Kurumları Sınavı) sonuçlarına göre "
            "ÖSYM (Ölçme, Seçme ve Yerleştirme Merkezi) yerleştirmesiyle başvurulur. "
            "How to apply: Undergraduate programs use YKS exam results placed by ÖSYM (Ölçme, Seçme ve Yerleştirme Merkezi). "
            "Başvuru süreci: YKS'ye girmek, tercih döneminde üniversiteyi seçmek, ÖSYM'nin yerleştirmesini beklemek. "
            "Tıp Fakültesine MF-3 puan türüyle, Mühendislik bölümlerine MF-4, Sağlık bilimleri bölümlerine TM veya MF puan türleriyle girilir. "
            "Kayıt tarihleri ÖSYM takvimi ile belirlenmektedir. "
            "Kesin kayıt için gerekli belgeler: lise diploması, YKS sonuç belgesi, nüfus cüzdanı, vesikalık fotoğraf. "
            "Uluslararası öğrenciler SAT, ACT veya kendi ülkelerinin ulusal sınavı ile başvurabilmektedir. "
            "Vakıf üniversitesi olup öğrenim ücretleri bölüme göre değişmektedir. "
            "YKS başarı sıralamasına göre %25, %50, %100 burs imkânları mevcuttur."
        ),
        "source": "seed",
    },
    # ── Tüm Bölümler listesi ─────────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/akademik/lisans/",
        "title": "Tüm Bölümler ve Programlar",
        "content": (
            "Hangi bölümler var? / What departments does Acibadem have? "
            "Bölümler (Departments): "
            "1. Tıp (Medicine) - 6 yıl (years), Türkçe (Turkish). "
            "2. Eczacılık (Pharmacy) - 5 yıl (years). "
            "3. Hemşirelik (Nursing). "
            "4. Fizyoterapi ve Rehabilitasyon (Physiotherapy & Rehabilitation). "
            "5. Beslenme ve Diyetetik (Nutrition & Dietetics). "
            "6. Sağlık Yönetimi (Health Management). "
            "7. Bilgisayar Mühendisliği (Computer Engineering). "
            "8. Biyomedikal Mühendisliği (Biomedical Engineering). "
            "9. Moleküler Biyoloji ve Genetik (Molecular Biology & Genetics). "
            "10. Psikoloji - Türkçe (Psychology - Turkish). "
            "11. Psikoloji - İngilizce (Psychology - English). "
            "12. Sosyoloji (Sociology). "
            "Toplam (Total): 11 lisans programı (undergraduate programs), 5 fakülte (schools)."
        ),
        "source": "seed",
    },
    # ── Lisansüstü Programlar ────────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/akademik/lisansustu/",
        "title": "Lisansüstü Programlar",
        "content": (
            "Lisansüstü programlar neler? Yüksek lisans (tezli/tezsiz): Klinik Psikoloji, Nörobilim, "
            "Sağlık Yönetimi, Tıbbi Biyoloji ve Genetik, Fizyoterapi ve Rehabilitasyon, "
            "Biyomedikal Mühendisliği, Endüstri Mühendisliği, Hemşirelik. "
            "Doktora programları: Tıbbi Biyoloji ve Genetik, Fizyoterapi, Hemşirelik. "
            "Başvuru için lisans diploması ve ALES sınavı gerekmektedir. "
            "Uluslararası öğrenciler GRE ile başvurabilmektedir."
        ),
        "source": "seed",
    },
    # ── Uluslararası Öğrenciler ──────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/uluslararasi-ofis/uluslararasi-ogrenciler/",
        "title": "Uluslararası Öğrenci Başvurusu",
        "content": (
            "Uluslararası öğrenciler nasıl başvurur? "
            "How can international students apply? "
            "SAT, ACT, Abitur, A-Level veya IB Diploma ile başvurabilirler. "
            "Ayrıca kendi ülkelerindeki ulusal üniversite sınavı sonuçları da kabul edilmektedir. "
            "Uluslararası öğrenciler için özel kontenjanlar mevcuttur. "
            "Yabancı uyruklu öğrenciler doğrudan üniversiteye başvurur; ÖSYM yerleştirmesine gerek yoktur. "
            "Başvuru ve öğrenim ücretleri için: uluslararasi@acibadem.edu.tr"
        ),
        "source": "seed",
    },
    # ── Erasmus ve Değişim ───────────────────────────────────
    {
        "url": "https://www.acibadem.edu.tr/uluslararasi-ofis/degisim-programlari/erasmus/",
        "title": "ERASMUS+ ve Değişim Programları",
        "content": (
            # Opening: bilingual FAQ anchors + contact within first ~200 chars for seed injection
            "Erasmus programı var mı? Evet. "
            "Uluslararası Ofis iletişim: uluslararasi@acibadem.edu.tr. "
            "Does Acibadem have an Erasmus program? Yes. "
            "Acıbadem University participates in ERASMUS+ and global exchange programs "
            "with partner universities in Europe, USA, Japan, and more. "
            # Mobility types
            "Değişim programları / Exchange programs: "
            "Öğrenci öğrenim hareketliliği (student learning mobility), "
            "öğrenci staj hareketliliği (student internship mobility), "
            "personel ders verme hareketliliği (staff teaching mobility), "
            "personel eğitim alma hareketliliği (staff training mobility). "
            # Eligibility — Turkish-first so TR queries answer in TR; English in parens for EN queries
            "Başvuru koşulları (Eligibility requirements): "
            "Lisans/ön lisans öğrencileri (Undergraduate/Associate): minimum not ortalaması GPA 2.20/4.00. "
            "Yüksek lisans/doktora öğrencileri (Graduate/PhD): minimum GPA 2.50/4.00. "
            "Birinci sınıf öğrencileri ve mezunlar başvuramaz (First-year students and graduates not eligible). "
            "Süre (Duration): minimum 2 ay (2 months), maksimum 12 ay (12 months). "
            "One semester = 30 ECTS / bir dönem 30 AKTS; one year = 60 ECTS / bir yıl 60 AKTS. "
            # Partners
            "Partner countries / Partner ülkeler: "
            "Erasmus+ (European countries) and global: USA, Albania, Brazil, Bulgaria, India, Japan, Georgia, Malaysia, Pakistan. "
            "Selected partner universities / Seçili partner üniversiteler: "
            "Medicine/Tıp: Heidelberg University (Germany), Medical University of Vienna (Austria), Medical University Sofia (Bulgaria). "
            "Nursing/Hemşirelik: Universita degli Studi di Foggia (Italy), Medical University of Plovdiv (Bulgaria). "
            # Coordinators
            "Institutional Erasmus Coordinator / Kurumsal Koordinatör: Prof. Dr. İrfan GÜNEY. "
            "Department coordinators / Bölüm koordinatörleri: "
            "Medicine/Tıp: Prof. Pınar TOPSEVER (pinar.topsever@acibadem.edu.tr), Prof. Özgür KURT; "
            "Pharmacy/Eczacılık: Prof. Umut BULUT (umut.bulut@acibadem.edu.tr); "
            "Physiotherapy/Fizyoterapi: Doç. Nuray ALACA (nuray.alaca@acibadem.edu.tr); "
            "Nursing/Hemşirelik: Prof. Ükke KARABACAK (ukke.karabacak@acibadem.edu.tr)."
        ),
        "source": "seed",
    },
]


class Command(BaseCommand):
    help = "Insert curated seed knowledge chunks for topics not well covered by scraping"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-insert even if a chunk with the same URL already exists",
        )

    def handle(self, *args, **options):
        force = options["force"]
        inserted = 0
        skipped = 0

        for entry in SEED_ENTRIES:
            url = entry["url"]

            # Get or create the WebPage record
            page, page_created = WebPage.objects.get_or_create(
                url=url,
                defaults={
                    "title": entry["title"],
                    "content": entry["content"],
                    "is_processed": True,
                    "source": entry.get("source", "seed"),
                },
            )

            if not page_created and force:
                page.title = entry["title"]
                page.content = entry["content"]
                page.is_processed = True
                page.source = entry.get("source", "seed")
                page.save(update_fields=["title", "content", "is_processed", "source"])

            # Check for existing chunks
            existing_chunks = DocumentChunk.objects.filter(web_page=page)
            if existing_chunks.exists() and not force:
                self.stdout.write(f"  SKIP (exists): {entry['title']}")
                skipped += 1
                continue

            if force:
                existing_chunks.delete()  # delete ALL old chunks, not just first

            # Generate embedding
            self.stdout.write(f"  Embedding: {entry['title']} ...")
            embedding = llm_service.get_embedding(entry["content"])

            chunk = DocumentChunk(
                web_page=page,
                content=entry["content"],
                chunk_index=0,
                token_count=len(entry["content"].split()),
            )
            if embedding:
                chunk.embedding = embedding
            chunk.save()

            inserted += 1
            status = "OK (embedded)" if embedding else "OK (no embedding — run generate_embeddings)"
            self.stdout.write(self.style.SUCCESS(f"  {status}: {entry['title']}"))

        self.stdout.write(
            self.style.SUCCESS(f"\nDone. Inserted: {inserted}, Skipped: {skipped}")
        )
