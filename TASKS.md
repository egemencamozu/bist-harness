# Görevler

## 1. Kurulum ve başlangıç doğrulaması

- [x] GitHub dalını, başlangıç commit'ini, depo yapısını ve bilgisayarı incele.
- [x] README, CLAUDE, video rehberi ve ilgili kaynak, yapılandırma, test, eğitim ve raporları incele.
- [x] Devam dosyalarını, atomik kayıt yordamını ve Release DB'de kesintiden devamı doğrula.
- [x] Yerel Git checkpoint'i kaydet (`31ec204`).
- [x] Python 3.12 ve kilitli uv ortamını hazırla. Release DB'yi SHA-256 ve SQLite bütünlük kontrolüyle doğrula.
- [x] Başlangıç pytest, Ruff lint/format, mypy ve şablonlu golden değerlendirmesini doğrula.
- [x] Ollama arşivini ve Release GGUF'u tamamla ve doğrula. Yerel model kaydı ve LLM/Harness duman testi yap (V07 geçti).

## 2. Transkript ve ingest

- [x] Egemen'in ikinci aşama onayını al ve sabit video listesini yerel girdilerle karşılaştır.
- [x] Beş Finans ve Borsa videosunun zaman damgalı transkriptlerini hazırla ve ayrıştırmayı doğrula.
- [x] TCMB ve Fed altyazılarını ve resmî referans metinlerini hazırla.
- [x] Doğrulanan girdilerle donmuş snapshot oluştur, ingest ve etiketleri test et (7 video, 181 segment, 334 test geçti).

## 3. İddia çıkarma ve insan incelemesi

- [x] Egemen'in üçüncü aşama geçiş onayını al.
- [x] Yerel çıkarımı, birebir kaynak doğrulamasını ve segment bazlı kesintiden devamı doğrula (337 test geçti).
- [x] Finans ve Borsa'nın beş videosunda 50 segmenti ve 54 inceleme adayının kaynak bağlantısını doğrula.
- [x] Fed ve TCMB dahil 181 segmentin çıkarımını tamamla ve 30 adaylık denetim örneklemini hazırla.
- [x] İnsan tarafından onaylanan 12 iddiayı dondur, aktar ve yayın tarihi sınırını doğrula.
- [x] 30 adayın bağlamsal Codex denetimini tamamla ve Wilson aralığını hesapla. Egemen'in 12 onayı ayrı kayıtta.

## 4. Deterministik doğrulama ve Point-in-Time

- [x] Sayısal sınır karşılaştırmasını ve ileri işlem penceresinin tarih kilidini saf hesaplama olarak test et.
- [x] 12 onaylı iddianın veri uygunluğunu incele ve ENKAI örneğinde yayın öncesi KAP karşılaştırmasını sınama amaçlı hesapla.
- [x] KAP ve makro sorgularına isteğe bağlı saat sınırı ekle. Aynı gün yayımlanan sonraki revizyonların görünmediğini test et.
- [x] Onaylı 12 iddia için kullanılabilir kanıtı ve doğrulamaya engel olan eksik girdileri sınıflandır.

- [x] Egemen'in onayladığı yöntemle deterministik doğrulama ve `get_speech_features` 1.1.0 çıktısını tamamla. 12 gerçek iddia doğrulama hattından geçti, 343 test başarılı.

## 5. MCP ve Harness entegrasyonu (aşama onayı bekliyor)

- [ ] MCP, Harness ve kanıt entegrasyonu. En az bir uçtan uca çalışma.

## 6. Nihai testler, değerlendirme ve rapor

- [ ] WER, Wilson güven aralığı, sonuç dağılımı ve sunum örneklerini `reports/speech_claims.md` içinde raporla. Final kontrolleri ve CLAUDE §14 kaydı.
