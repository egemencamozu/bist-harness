# Son çalışma durumu

## 26 Kasım 2026

Uzak dal ve `1f1d00f6997b0b880219809f162b9c6a8cf4836b` başlangıç sürümü doğrulandı. Çalışma klasörü ilk kontrolde boştu. Rehberler ve konuşma katmanının uygulama noktaları incelendi. Release listesi doğrulandı.

Git for Windows ve uv kuruldu. Uzak dal yerelde izleniyor. Atomik checkpoint yazımı, eşzamanlı yazma engeli, yarım geçici kaydın yok sayılması ve girdi kimliği değişimi doğrulandı. Release DB indirmesi 1.048.576 bayttan devam etti. Sıkıştırılmış dosya ve kurulu `data/db/bist.sqlite` SHA-256 ile doğrulandı.

## Sonraki adım

`CHECKPOINT.json` ve Git durumunu doğrula. GGUF ve Ollama indirmelerinin durumuna, ardından başlangıç testlerine bak. Faz doğrulamaları ile Egemen onaylarını kaydet.

`powershell -NoProfile -ExecutionPolicy Bypass -File setup\checkpoint.ps1` son güvenli kaydı gösterir. `powershell -NoProfile -ExecutionPolicy Bypass -File setup\resume_assets.ps1` Release DB ve modeli doğrular veya yarım indirmeye devam eder. `-SkipModel` ile yalnız DB hazırlanır. Kesinti sonrası etkin bir indirme varsa aynı işlemi ikinci kez başlatmadan önce durumu kontrol et.

## Uzun işleri sürdürme

`CHECKPOINT.json` ortak durumun küçük bir özetidir. Gerçek dosya boyu ve SHA-256 kayıttan önce doğrulanır. Geçersiz kayıt veya yarım sonuç başarı sayılmaz. `in_progress` yeniden başlanabilir işi, `failed` son geçerli denemenin hatasını, `completed` doğrulanmış çıktıyı gösterir. Yarım Release dosyaları `.assets/` içinde SHA-256 kimlikli yollarında durur. Aynı varlık tekrar çağrıldığında HTTP Range destekleniyorsa aynı dosyadan devam edilir. Dosyanın tamamı Release SHA-256 ile karşılaştırılır. Kurulu DB ingest sonrası değişebileceği için farklı içerikli kurulu varlık için operatör kararı gerekir.

Speech çıkarımı uygulanırken segment kimliğini kaynak, zaman aralığı, yayım zamanı, metin ve etiketlerin kanonik hash'iyle oluştur. Yeniden kullanım ayrıca model digest'i, prompt, JSON şeması, çıkarım ayarları ve normalizasyon sürümü eşleşmesini gerektirir. Sonuç ve iş durumunu tek işlemde kalıcılaştır. Şema ve kaynak denetiminden geçmiş boş liste de tamamlanmış sonuçtur. Kesilmiş, hatalı veya onaysız sonuçlar kendi durumunda kalır. İnceleme durumunu sonuç hash'ine bağla. Değişen segment ve bağımlılıkları yeniden işle. Çıktı ve inceleme verisini Git dışında tut. Bu ayrıntılar çıkarım aşamasında test edilecek.
