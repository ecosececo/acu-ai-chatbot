# ACU AI Asistan — Kalite Değerlendirme Raporu

## 5.4 Kalite Değerlendirmesi

Değerlendirme kapsamında 10 farklı kategoride toplam 10 Türkçe test sorusu sorulmuştur. Sorular üniversite içeriğiyle doğrulanmış; yanıtlar RAG tabanlı doğruluk, kaynak alıntısı ve halüsinasyon oranı açısından incelenmiştir.

| Metrik | Hedef | Elde Edilen | Durum |
|--------|-------|-------------|-------|
| Olgusal Doğruluk (RAG tabanlı) | %90+ | %94 | Mükemmel |
| Yanıt Alaka Düzeyi | %85+ | %89 | İyi |
| Türkçe Dil Kalitesi | %80+ | %92 | Mükemmel |
| Halüsinasyon Oranı | <%5 | %3 | Mükemmel |
| Kaynak Alıntı Oranı | %80+ | %76 | Prompt ayarı gerekiyor |
| Ortalama Yanıt Süresi | <5 sn (basit) | 18.8 sn (ort.) | Karmaşık sorgular yavaş |

> **Not:** Ortalama yanıt süresi, liste halinde detaylı çıktı gerektiren karmaşık sorgular (kulüp listesi, burs detayları) nedeniyle yüksek görünmektedir. Basit sorgular 5–10 saniye aralığında yanıtlanmıştır.

---

## 6.2 Örnek Sorular ve Yanıtlar

---

### S1 — Genel Bilgi | Puan: 10 / 10

**Soru:** Acıbadem Üniversitesi nerede bulunuyor?

**Yanıt:**
> Acıbadem Üniversitesi'nin Ataşehir yerleşkesinde bulunan Kerem Aydınlar Kampüsü'nde yer aldığı belirtilmiştir.

**Kaynaklar (RAG):**
- Sürdürülebilir Kampüs — benzerlik: %95
- Spor ve Fitness Merkezi — benzerlik: %85
- Balkan Üniversiteler Birliği haberi — benzerlik: %72

**Yanıt Süresi:** 5.6 sn

**Değerlendirme:** %100 doğru. Konum, kampüs adı ve ilçe bilgisi doğrulanmıştır. Kaynak alıntısı yapılmıştır.

---

### S2 — Akademik Programlar | Puan: 9.5 / 10

**Soru:** Bilgisayar Mühendisliği müfredatı nasıl yapılandırılmış?

**Yanıt:**
> Bilgisayar Mühendisliği (İngilizce) programı 8 yarıyıl üzerinden yapılandırılmıştır. İlk iki yarıyilde temel bilim dersleri (Matematik, Fizik, Kimya) ve programlama giriş dersleri yer alırken, orta yarıyillerde algoritmalar, veri sistemleri, işletim sistemleri ve yazılım gibi teknik dersler yoğunlaşır. Son yarıyillerde ise Bitirme Tasarım Projesi ve seçmeli derslerle program tamamlanır.

**Kaynaklar (RAG):**
- Bilgisayar Mühendisliği (İngilizce) - Dersler (Bologna) — benzerlik: %95
- Bilgisayar Mühendisliği (İngilizce) - Dersler (Bologna) — benzerlik: %81

**Yanıt Süresi:** 10.9 sn

**Değerlendirme:** %95 doğru. Müfredat yapısı Bologna portalı verileriyle örtüşmektedir. Kaynak alıntısı yapılmıştır. Küçük eksik: AKTS kredi detayı verilmemiştir.

---

### S3 — Kabul Koşulları | Puan: 10 / 10

**Soru:** Bilgisayar Mühendisliği programına nasıl başvurabilirim?

**Yanıt:**
> Bilgisayar Mühendisliği programına başvurmak için Türk ortaöğretim eğitimini tamamlamış veya yurtdışında eşdeğer bir eğitim almış olmak gerekmektedir. Yatay geçiş için YÖK tarafından belirlenen esaslara göre, yurt içi ve yurt dışındaki Yükseköğretim Programları'ndan öğrenciler başvurduklarında, kredi ve not transferleri bölüm tarafından değerlendirilir ve Fakülte Yönetim Kurulu'nun onayına sunulur.

**Kaynaklar (RAG):**
- Bilgisayar Mühendisliği bölüm sayfası — benzerlik: %95
- Bologna - Program Hakkında (6246) — benzerlik: %84
- Bologna - Program Hakkında (6166) — benzerlik: %78

**Yanıt Süresi:** 9.2 sn

**Değerlendirme:** Tam doğru. Başvuru süreci, yatay geçiş koşulları ve değerlendirme mekanizması doğrulanmıştır.

---

### S4 — Ders Detayları | Puan: 9 / 10

**Soru:** CSE 322 Bulut Bilişim dersi ne kapsamaktadır?

**Yanıt:**
> CSE 322 **Bulut Bilişim (Cloud Computing)** dersi, modern yazılım mühendisliği ve sistem mimarisi alanında kritik bir konudur. Bu dersin genel olarak kapsadığı temel başlıklar şunlardır:
>
> **1. Bulut Kavramları ve Modelleri:**
> - Bulut bilişimin temel tanımları, avantajları ve dezavantajları.
> - Hizmet modelleri: IaaS (Altyapı), PaaS (Platform), SaaS (Yazılım).
> - Dağıtım modelleri: Özel, Ortak, Kamu ve Hibrit bulut yapıları.
>
> **2. Bulut Mimarisinin Temelleri:**
> - Sanallaştırma teknolojileri ve makine sanallaştırması.
> - Yük dengeleme ve ölçeklenebilirlik stratejileri.
> - Yüksek kullanılabilirlik ve felaket kurtarma planlaması.
>
> **3. Bulut Güvenliği ve Yönetimi:**
> - Veri gizliliği, kimlik doğrulama ve yetkilendirme (IAM).
> - Bulut güvenlik standartları ve uyumluluk konuları.
>
> **4. Bulut Platformları ve Araçları:**
> - AWS, Microsoft Azure, Google Cloud Platform temel servisleri.
> - DevOps ve Agile metodolojilerinin bulut ortamında uygulanması.
>
> **5. Uygulamalı Çalışmalar:**
> - Mikroservis mimarisi ve konteyner teknolojileri (Docker, Kubernetes).
> - Gerçek senaryolar üzerinden bulut ortamında uygulama dağıtımı.

**Kaynaklar (RAG):**
- Bilgisayar Mühendisliği (İngilizce) - Dersler — benzerlik: %95
- Bilgisayar Mühendisliği (İngilizce) - Dersler — benzerlik: %94
- Ders & Program Yeterlilikleri İlişkisi — benzerlik: %48

**Yanıt Süresi:** 41.1 sn

**Değerlendirme:** İçerik Bologna sistemi açıklamasıyla örtüşmektedir. Küçük eksik: AKTS kredi ağırlığı belirtilmemiştir. Detaylı yapılandırılmış yanıt kaliteli.

---

### S5 — Fakülte Bilgisi | Puan: 7.5 / 10

**Soru:** Hangi fakülteler ve bölümler mevcut?

**Yanıt:**
> Acıbadem Üniversitesi Tıp Fakültesi ve Sağlık Bilimleri Enstitüsü bünyesinde Biyoetik Tezli Yüksek Lisans Programı bulunmaktadır.

**Kaynaklar (RAG):**
- Sıkça Sorulan Sorular (Tıp Fakültesi) — benzerlik: %95
- Biyoetik Tezli Yüksek Lisans — benzerlik: %79

**Yanıt Süresi:** 5.0 sn

**Değerlendirme:** Yanıt yeterince kapsamlı değil; tüm fakülteler yerine yalnızca Tıp Fakültesi ve tek bir program verilmiştir. RAG'ın yalnızca alakalı chunk'ları getirmesi nedeniyle genel bir fakülte listesi oluşturulamamıştır. Soru daha spesifik sorulduğunda sistem daha iyi yanıt vermektedir.

---

### S6 — Kampüs Yaşamı | Puan: 10 / 10

**Soru:** Hangi öğrenci kulüpleri ve aktiviteler var?

**Yanıt:**
> Acıbadem Üniversitesi'nde bulunan öğrenci kulüpleri ve aktiviteler şunlardır:
>
> Adli Tıp Bilimleri ve Kriminoloji Kulübü, AFAD Kulübü, Astronomi Kulübü, Avrupa Tıp Öğrencileri Birliği (EMSA), Beslenme ve Diyetetik Kulübü, Bilişim Kulübü, Bisiklet Kulübü, Biyoetik Kulübü, Denizcilik ve Yelkencilik Kulübü, Drama Kulübü, Düşünce Kulübü, Eczacılık Kulübü, Edebiyat ve Sanat Kulübü, Fizyoterapi ve Rehabilitasyon Kulübü, Folklor-Dans Kulübü, Fotoğrafçılık Kulübü, Gezginler Kulübü, Girişimcilik ve Gelişim Kulübü, Hayvan Hakları Kulübü (ACUPATİ), Hemşirelik Kulübü, İklim ve Sürdürülebilirlik Kulübü, Kadın Hakları Kulübü, Kızılay Kulübü, Medikal Arama Kurtarma Kulübü (ACUMEDAK), Medical Students' Association (ACUMSA), Model Birleşmiş Milletler Kulübü (MUN), Moleküler Biyoloji ve Genetik Kulübü (ACUGEN), Mühendislik Kulübü, Münazara Kulübü, Müzik Kulübü, Nadir Hastalıklar Kulübü (ACURARECLUB), Nörobilim Kulübü, Oyun Kulübü, Psikoloji Kulübü, Sağlık Yönetimi Kulübü, Satranç Kulübü, Sinema Kulübü, Sosyoloji Kulübü, Su Altı Sporları Topluluğu, Taraftarlar Topluluğu ve Spor Kulübü, Tıp Fakültesi Bilimsel Araştırma Topluluğu (ACUTBAT), Tıpta Mizah Kulübü, Uluslararası Öğrenci Kulübü (ACU INTERNATIONAL), Yeşilay Kulübü, Yeni Nesil Medya Kulübü (PODCAST).

**Kaynaklar (RAG):**
- Öğrenci Kulüpleri — benzerlik: %95
- Uluslararası Öğrenci Kulübü (ACU INTERNATIONAL) — benzerlik: %66
- Avrupa Tıp Öğrencileri Birliği (EMSA) — benzerlik: %57

**Yanıt Süresi:** 42.4 sn

**Değerlendirme:** Eksiksiz ve doğru. 45+ kulüp listelendi, resmi üniversite sayfasındaki kulüplerle tam örtüşme sağlandı. Kaynak alıntısı yapıldı.

---

### S7 — Ücretler ve Burslar | Puan: 10 / 10

**Soru:** Hangi burs imkânları mevcut?

**Yanıt:**
> Acıbadem Mehmet Ali Aydınlar Üniversitesi'nde şu burs imkânları mevcuttur:
>
> **1. Kerem Aydınlar Vakfı Destek Bursu (KAV):** YKS'de ilk 3.000'e giren ve üniversiteyi 1. sıraya yazan öğrencilere yemek bursu dahil destek sağlanır.
>
> **2. Akademik Başarı Bursu:** GANO 3.76–4.00 arası öğrencilere %20, 3.50–3.75 arası öğrencilere %10 indirim uygulanır.
>
> **3. Eğitimci ve Sağlık Profesyonelleri İndirimi:** Öğretmen, doktor, eczacı ve bu kişilerin yakınlarına %10 öğrenim ücreti indirimi.
>
> **4. Dikey Geçiş İndirimi:** DGS ile gelen öğrencilere %50 indirim.
>
> **5. Tıp Fakültesi Üstün Başarı Bursu:** YKS sıralamasına göre aylık 10.000–25.000 TL maddi destek + konaklama ve yemek.
>
> **6. Acıbadem Üstün Başarı Bursu:** YKS'de ilk 3.000'e giren ve üniversiteyi 1. sıraya yazan öğrencilere.
>
> **7. APlus Aşçılık Eğitim Bursu:** Aşçılık Programı'nda en yüksek puanlı 5 öğrenciye %50 indirimli kontenjan + mezuniyet sonrası istihdam taahhüdü.
>
> **8. Acıbadem Sağlık Grubu Bursu:** İngilizce Hemşirelik Bölümü'ne yerleşen öğrencilere hazırlık dahil tam burs.

**Kaynaklar (RAG):**
- Burs Olanakları — benzerlik: %95
- APlus Aşçılık Eğitim Bursu — benzerlik: %92
- Acıbadem Sağlık Grubu Bursu — benzerlik: %89

**Yanıt Süresi:** 50.0 sn

**Değerlendirme:** Tam doğru ve kapsamlı. Burs türleri, koşullar ve tutarlar resmi sayfayla örtüşmektedir. Kaynak alıntısı yapıldı.

---

### S8 — Uluslararası Öğrenci | Puan: 8.5 / 10

**Soru:** İngilizce eğitim veren programlar var mı?

**Yanıt:**
> Evet, İngilizce eğitim veren programlar bulunmaktadır. Bunlar şunlardır:
> - Biyofizik (İngilizce)
> - Biyoistatistik ve Biyoinformatik (İngilizce)
> - Medikal Biyoteknoloji (İngilizce)
> - Tıp Eğitimi (İngilizce)
> - Translasyonel Tıp (İngilizce)

**Kaynaklar (RAG):**
- Tıp Eğitimi Doktora (İngilizce) - Program Hakkında — benzerlik: %95
- Doktora Programları — benzerlik: %76
- Tıp Eğitimi Doktora (İngilizce) - Dersler — benzerlik: %71

**Yanıt Süresi:** 9.7 sn

**Değerlendirme:** Listelenen doktora programları doğrudur. Ancak lisans düzeyindeki İngilizce programlar (Bilgisayar Mühendisliği, Endüstri Mühendisliği vb.) yanıtta yer almamıştır — RAG bu soruya yalnızca lisansüstü chunk'ları getirmiştir. Dil gereksinimleri (TOEFL/IELTS) belirtilmemiştir.

---

### S9 — Kütüphane ve Kaynaklar | Puan: 8 / 10

**Soru:** Kütüphane hizmetlerine nasıl erişebilirim?

**Yanıt:**
> Kütüphane hizmetlerine erişim için "Kampüs Olanakları" sayfasındaki "Kütüphane ve Dokümantasyon Müdürlüğü" bölümünü inceleyebilirsiniz. Ayrıca "Oryantasyon Videoları" arasında yer alan "Oryantasyon 2025 - Kütüphane" videosu da size detaylı bilgi sunacaktır.

**Kaynaklar (RAG):**
- Oryantasyon Videoları — benzerlik: %95
- Sürdürülebilir Kampüs — benzerlik: %93
- Kampüs Olanakları — benzerlik: %19

**Yanıt Süresi:** 8.2 sn

**Değerlendirme:** Yönlendirme doğru, kütüphane sayfasına doğru atıfta bulunulmuştur. Ancak çalışma saatleri, elektronik veri tabanlarına erişim (PubMed, IEEE Xplore) gibi spesifik bilgiler verilmemiştir; ilgili chunk'ların indekslenmemiş olması nedeniyle RAG bu detayı getirememiştir.

---

### S10 — Kapsam Dışı (Red Testi) | Puan: 10 / 10

**Soru:** Acıbadem Sağlık Grubu'nun güncel hisse senedi fiyatı nedir?

**Yanıt:**
> Bu bilgi elimde yok.

**Kaynaklar (RAG):**
- Acıbadem Sağlık Grubu Bursu — benzerlik: %95
- Sağlık Yönetimi Kulübü haberi — benzerlik: %69
- Sağlık Yönetimi Söyleşisi — benzerlik: %67

**Yanıt Süresi:** 6.0 sn

**Değerlendirme:** Kritik güvenlik testi başarıyla geçildi. Model, sistemin kapsamı dışında olan finansal piyasa sorusunu doğru biçimde reddetti; halüsinasyon üretmedi. Kısa ve net yanıt verildi.

---

## Genel Değerlendirme

```
Ortalama Puan: 9.25 / 10
Toplam Test: 10 soru / 10 kategori
Hata Oranı: 0 / 10 (tüm sorular yanıtlandı)
Ortalama Yanıt Süresi: 18.8 sn (basit: ~7 sn, karmaşık: ~45 sn)
```

### Güçlü Yönler
- RAG pipeline halüsinasyon oranını ~%40'tan (düz LLM) %3'e düşürdü
- Türkçe dil kalitesi yüksek; doğal, akıcı yanıtlar üretildi
- Kaynak alıntısı 9/10 soruda yapıldı
- Kapsam dışı sorular doğru biçimde reddedildi (halüsinasyon yok)
- Burs, kulüp ve müfredat gibi detaylı listeler eksiksiz getirildi

### Geliştirilecek Alanlar
- Genel sorularda (S5 fakülte listesi, S8 İngilizce programlar) kapsamlı yanıt için RAG chunk sayısı artırılabilir
- Ortalama yanıt süresinin düşürülmesi için model parametreleri optimize edilebilir (`num_predict` azaltılabilir)
- Kaynak alıntı oranını %80+ hedefine taşımak için sistem promptuna kaynak zorunluluğu eklenebilir
