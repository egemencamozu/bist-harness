# Proje bağlamı

CSE-481 projesi, BIST sorularını donmuş fiyat, KAP, makro ve haber verisiyle analiz eder. Varsayılan model Qwen3.5-4B QLoRA tabanlı `bist-analist` GGUF Q8_0'dır. Model açıklama ve öneri üretir. Analitik katman hesapları, harness kanıt denetimini ve risk kapısını, insan son kararı yürütür.

İncelenen başlangıç commit'i `1f1d00f6997b0b880219809f162b9c6a8cf4836b`. `core/pit.py` bilgi zamanına göre SQL filtreleri ve son kontrol uygular. `data/ingest/speech.py` sabit listedeki yedi video için transkript ayrıştırma, segmentleme, etiketleme, WER ve donmuş snapshot oluşturmayı sağlar. `tools/context.py` içindeki `get_speech_features` segment metadatasını verir. Harness politika haritasında bu araç izinlidir. Varsayılan planlayıcı bu durumda haber aracını çağırır. İddia çıkarma, insan onayı, iddia tablosu, doğrulama ve rapor aşamaları bekliyor.

`config/news.yaml` etiketlemede, `config/settings.yaml` veri yolunda, `config/harness_policy.yaml` araç ve çıkarım politikasında kullanılır. `training/` ayrı QLoRA ortamı ve dışa aktarım içerir. `eval/` golden, dayanıklılık, bakeoff ve ablasyon araçlarını içerir. Depodaki `reports/golden_final.json` önceki ortamda 5/5 sonucu kaydediyor. Yerel doğrulama ayrı kaydedilir.

Windows 10 Pro 22H2 x64, i5-12500H (12 çekirdek, 16 iş parçacığı), 15,7 GiB RAM, RTX 3050 Laptop 4 GiB VRAM, NVIDIA 595.95. İlk kontrolde E: üzerinde yaklaşık 170 GiB boş alan görüldü. Yerel Windows kurulumu kullanılacak. 4 GiB VRAM üzerinde Q8_0 modelin CPU ve RAM kullanımı ile gecikmesi ölçülecek. Referans raporlar 8 GiB VRAM'li ortamda elde edildi.

GitHub API, depoyu ve `assets-2026-11-20` Release'ini herkese açık gösterdi. Release'te sağlama dosyası, yaklaşık 14,6 MB sıkıştırılmış DB ve toplam yaklaşık 4,48 GB olan üç GGUF parçası var. Rehberin gizli depo bilgisi önceki durumu yansıtıyor.
