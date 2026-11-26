# Son çalışma durumu

`DURUM.cmd` açıkken görevleri ve diskteki indirme baytlarını 10 saniyede bir yeniler. İndirme tahmini gözlenen hıza göre değişir. Aşama ve görev durumları `TASKS.md` içindeki işaretlerden gelir.

## 26 Kasım 2026

Uzak dal ve `1f1d00f6997b0b880219809f162b9c6a8cf4836b` başlangıç sürümü doğrulandı. Çalışma klasörü ilk kontrolde boştu. Rehberler ve konuşma katmanının uygulama noktaları incelendi. Release listesi doğrulandı.

Git for Windows ve uv kuruldu. Uzak dal yerelde izleniyor. Atomik checkpoint yazımı, eşzamanlı yazma engeli, yarım geçici kaydın yok sayılması ve girdi kimliği değişimi doğrulandı. Release DB indirmesi 1.048.576 bayttan devam etti. Sıkıştırılmış dosya ve kurulu `data/db/bist.sqlite` SHA-256 ile doğrulandı. İlk yerel Git checkpoint'i `31ec204`.

Python 3.12.16 ve kilitli 76 paket hazır. Release DB için SQLite `quick_check` sonucu `ok`. Son işlem günü 19 Kasım 2026 ve konuşma segmenti sayısı 0. pytest 334/334, Ruff lint ve format başarılı, mypy 75 kaynak dosyasında temiz, şablonla golden 5/5. Testler `.venv` içerisindeki araçlarla çalıştırıldı.

Ollama 0.40.17 arşivi ile GGUF parça indirmesi başladı. Son ölçümde sırasıyla yaklaşık 206 MiB ve ilk GGUF parçasında 232 MiB kısmi çıktı vardı. Yerel model kaydı ve LLM'li Harness duman testi tamamlanmayı bekliyor. Kısmi bayt sayısını `.assets/` altındaki ilgili dosyadan kontrol et.

## Sonraki adım

`CHECKPOINT.json` ve Git durumunu doğrula. GGUF ve Ollama indirmelerini tamamla, modelin yerel kaydını ve LLM'li Harness duman testini yap. Çalışma süresini ve sonucu kaydet. Başlangıç fazı doğrulandıktan sonra Egemen onayıyla transkript hazırlığına geç.

`powershell -NoProfile -ExecutionPolicy Bypass -File setup\checkpoint.ps1` son güvenli kaydı gösterir. JSON doğrulaması başarısız olursa `git show HEAD:CHECKPOINT.json` ile son yerel Git kaydını oku ve dosya sağlama toplamlarını yeniden kontrol et. `powershell -NoProfile -ExecutionPolicy Bypass -File setup\resume_assets.ps1` Release DB ve modeli doğrular veya yarım indirmeye devam eder. `-SkipModel` ile yalnız DB hazırlanır. Kesinti sonrası etkin bir indirme varsa aynı işlemi ikinci kez başlatmadan önce durumu kontrol et.

`powershell -NoProfile -ExecutionPolicy Bypass -File setup\resume_assets.ps1 -OllamaRuntime` sabit sürümün Windows paketini doğrulayıp `.tools/ollama-0.40.17` altına açar. WinGet bu sürümü listelemedi. Proje bağımlılıkları için `UV_CACHE_DIR=.tools/uv-cache` ve `UV_PYTHON_INSTALL_DIR=.tools/python` ortam değişkenlerini proje kökünü baz alarak ayarla. `uv sync --locked --python 3.12 --extra dev --extra llm --extra ui --extra mcp` komutuyla aynı ortamı sürdür.

Model ve çalışma zamanı doğrulandıktan sonra yerel Ollama hizmetinin mevcut durumunu denetle. Gerekirse `OLLAMA_HOST=127.0.0.1:11434` ve proje altındaki `.tools/ollama-models` yoluyla `OLLAMA_MODELS` ayarlayarak `.tools/ollama-0.40.17/ollama.exe serve` başlat. Release GGUF'u `setup/get_assets.ps1` içindeki Modelfile ayarlarıyla kaydet. Mevcut aynı adlı modelin kaynağını kontrol et. `ollama show bist-analist --modelfile` ve harness duman testiyle doğrula.

## Uzun işleri sürdürme

`CHECKPOINT.json` ortak durumun küçük bir özetidir. Gerçek dosya boyu ve SHA-256 kayıttan önce doğrulanır. Geçersiz kayıt veya yarım sonuç başarı sayılmaz. `in_progress` yeniden başlanabilir işi, `failed` son geçerli denemenin hatasını, `completed` doğrulanmış çıktıyı gösterir. Yarım Release dosyaları `.assets/` içinde SHA-256 kimlikli yollarında durur. Aynı varlık tekrar çağrıldığında HTTP Range destekleniyorsa aynı dosyadan devam edilir. Dosyanın tamamı Release SHA-256 ile karşılaştırılır. Kurulu DB ingest sonrası değişebileceği için farklı içerikli kurulu varlık için operatör kararı gerekir.

Speech çıkarımı uygulanırken segment kimliğini kaynak, zaman aralığı, yayım zamanı, metin ve etiketlerin kanonik hash'iyle oluştur. Yeniden kullanım ayrıca model digest'i, prompt, JSON şeması, çıkarım ayarları ve normalizasyon sürümü eşleşmesini gerektirir. Sonuç ve iş durumunu tek işlemde kalıcılaştır. Şema ve kaynak denetiminden geçmiş boş liste de tamamlanmış sonuçtur. Kesilmiş, hatalı veya onaysız sonuçlar kendi durumunda kalır. İnceleme durumunu sonuç hash'ine bağla. Değişen segment ve bağımlılıkları yeniden işle. Çıktı ve inceleme verisini Git dışında tut. Bu ayrıntılar çıkarım aşamasında test edilecek.
