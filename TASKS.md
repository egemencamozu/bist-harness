# Görevler

## 1. Kurulum ve başlangıç doğrulaması

- [x] GitHub dalını, başlangıç commit'ini, depo yapısını ve bilgisayarı incele.
- [x] README, CLAUDE, video rehberi ve ilgili kaynak, yapılandırma, test, eğitim ve raporları incele.
- [x] Devam dosyalarını, atomik kayıt yordamını ve Release DB'de kesintiden devamı doğrula.
- [x] Yerel Git checkpoint'i kaydet (`31ec204`).
- [x] Python 3.12 ve kilitli uv ortamını hazırla. Release DB'yi SHA-256 ve SQLite bütünlük kontrolüyle doğrula.
- [x] Başlangıç pytest, Ruff lint/format, mypy ve şablonlu golden değerlendirmesini doğrula.
- [ ] Ollama arşivini ve Release GGUF'u tamamla ve doğrula. Yerel model kaydı ve LLM/Harness duman testi yap.

Ollama ve ilk GGUF parçası doğrulandı. İkinci parça ağ kesintisi sonrası kaldığı bayttan sürüyor. Üçüncü parça ve yerel model testi bekliyor.

## 2. Transkript ve ingest

- [ ] Sabit listedeki beş FB transkriptini ve mevcutsa TCMB/Fed altyazı ve resmî metinlerini rehbere göre hazırla. Donmuş ingest ve etiketleri doğrula.

## 3. İddia çıkarma ve insan incelemesi

- [ ] Segment bazlı yerel iddia çıkarma, kaynak doğrulaması, kesintiden devam, insan incelemesi ve PIT iddia okuması. Test ve kesinlik denetimi.

## 4. Deterministik doğrulama ve Point-in-Time

- [ ] Egemen'in onayladığı doğrulama metodolojisi ve araç sözleşmesiyle deterministik doğrulama ve PIT testleri.

## 5. MCP ve Harness entegrasyonu

- [ ] MCP, Harness ve kanıt entegrasyonu. En az bir uçtan uca çalışma.

## 6. Nihai testler, değerlendirme ve rapor

- [ ] WER, Wilson güven aralığı, sonuç dağılımı ve sunum örneklerini `reports/speech_claims.md` içinde raporla. Final kontrolleri ve CLAUDE §14 kaydı.
