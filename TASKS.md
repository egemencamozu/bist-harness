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

- [ ] Aşama geçiş onayıyla segment bazlı yerel iddia çıkarma, kaynak doğrulaması, kesintiden devam, insan incelemesi ve PIT iddia okuması. Test ve kesinlik denetimi.

## 4. Deterministik doğrulama ve Point-in-Time

- [ ] Egemen'in onayladığı doğrulama metodolojisi ve araç sözleşmesiyle deterministik doğrulama ve PIT testleri.

## 5. MCP ve Harness entegrasyonu

- [ ] MCP, Harness ve kanıt entegrasyonu. En az bir uçtan uca çalışma.

## 6. Nihai testler, değerlendirme ve rapor

- [ ] WER, Wilson güven aralığı, sonuç dağılımı ve sunum örneklerini `reports/speech_claims.md` içinde raporla. Final kontrolleri ve CLAUDE §14 kaydı.
