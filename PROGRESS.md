# Son çalışma durumu

`DURUM.cmd` açıkken görevleri ve diskteki indirme baytlarını 10 saniyede bir yeniler. İndirme tahmini gözlenen hıza göre değişir. Aşama ve görev durumları `TASKS.md` içindeki işaretlerden gelir.

## 26 Kasım 2026

Uzak dal ve `1f1d00f6997b0b880219809f162b9c6a8cf4836b` başlangıç sürümü doğrulandı. Çalışma klasörü ilk kontrolde boştu. Rehberler ve konuşma katmanının uygulama noktaları incelendi. Release listesi doğrulandı.

Git for Windows ve uv kuruldu. Uzak dal yerelde izleniyor. Atomik checkpoint yazımı, eşzamanlı yazma engeli, yarım geçici kaydın yok sayılması ve girdi kimliği değişimi doğrulandı. Release DB indirmesi 1.048.576 bayttan devam etti. Sıkıştırılmış dosya ve kurulu `data/db/bist.sqlite` SHA-256 ile doğrulandı. İlk yerel Git checkpoint'i `31ec204`.

Python 3.12.16 ve kilitli 76 paket hazır. Release DB için SQLite `quick_check` sonucu `ok`. Son işlem günü 19 Kasım 2026 ve konuşma segmenti sayısı 0. pytest 334/334, Ruff lint ve format başarılı, mypy 75 kaynak dosyasında temiz, şablonla golden 5/5. Testler `.venv` içerisindeki araçlarla çalıştırıldı.

Ollama 0.40.17 kuruldu. Ağ kesintileri sonrası devam eden üç parçalı GGUF indirmesi tamamlandı. Birleştirilmiş 4.482.403.040 baytlık dosyanın SHA-256 değeri Release ile eşleşti. `bist-analist:latest` yerel Ollama'ya kaydedildi. `/api/show` üzerinden modelin kayıtlı GGUF kimliği doğrulandı. Ollama yalnızca `127.0.0.1:11434` üzerinde çalışıyor ve bulut erişimi kapalı.

Yerel Harness V07 uçtan uca testi 273,7 saniyede geçti. Hafta örüntüsü doğru tanındı, model dört araç çağrısı planladı, geçersiz çağrı görülmedi ve açıklama ilk denetimden geçti. Koşu sırasında Ollama CPU/GPU dağılımını %58/%42 olarak gösterdi. Test komutu `.venv\Scripts\python.exe -m eval.robustness --set v2 --e2e --only V07 --models bist-analist --intent llm --out .assets/baseline-smoke`. Yerel sonuç `.assets/baseline-smoke/v2/e2e_bist-analist.json` dosyasında.

Egemen ikinci aşamaya geçişi onayladı. Sabit listedeki yedi videonun YouTube transkript panelindeki zaman damgalı metinleri kaydedildi. TCMB konuşma metni ve Fed basın toplantısı transkripti referans olarak eklendi. Listedeki iki resmî videonun URL'si doğrulandı.

`speech-2026-11-26-45f5eb9c38` ingest kaydı yedi kaynaktan 181 segment içeriyor. SHA-256 manifesti 10 girdiyle doğrulandı. TCMB altyazısı için WER %4,5, Fed altyazısı için %1,6. Beş Finans ve Borsa videosunda mevcut kalite kuralı TCMB ölçümünü vekil olarak kullanır. Gerçek veride yedi video için yayın tarihinden önceki gün boş sonuç verdi, yayın gününde segmentler erişilebildi. Bilanço videosunun THYAO etiketi doğrulandı. Aynı videodaki kısaltılmış Coca-Cola adı mevcut CCOLA sözlüğüne uymadığı için etiketlenmedi.

Ingest öncesi SQLite yedeği `.assets/pre-speech-ingest-2026-11-26.sqlite` konumunda. Ingest sonrası veri bütünlüğü ve diğer tabloların içeriği yedeğe karşı denetlendi. Ruff lint ve biçim kontrolleri ile mypy geçti. İlk pytest koşusundaki Windows geçici klasörü erişim sorunu, proje içinde ayrı bir `--basetemp` kullanılarak giderildi. Tam koşuda 334 test geçti.

## Sonraki adım

PITRepository'nin KAP ve makro okumalarına isteğe bağlı İstanbul saati sınırı eklendi. Sınır SQL'de revizyon seçilmeden önce uygulanır ve as_of gün sonunu aşamaz. 46 PIT, doğrulama ve mevcut araç testi, Ruff ve mypy geçti. Bu destek mevcut araç sözleşmelerine eklenmedi.

Onaylı 12 aday için veri hazırlığı:

| Aday | Sayı | Doğrulama girdisi |
|---|---:|---|
| ENKAI yıllık hasılat | 1 | Yayından önce açıklanan 1566104 numaralı raporda aynı konsolide tablonun cari ve karşılaştırmalı 12 aylık değerleri var. |
| Fiyat, Pro veya F skoru | 5 | Skor kaynağı ve formülü bu iddialarda belirtilmiyor. CCOLA ve bir DOHOL kaydında model metriği alıntıdaki skor adıyla da uyuşmuyor. |
| CCOLA değerleme çarpanları | 1 | Tek alıntıda birden fazla oran var. Her oran ayrı metrik ve tarih bağlamıyla eşlenmeli. |
| Makro aktarım ifadeleri | 2 | Faiz ve enflasyon ilişkisine dair genel ifadeler. Sınanacak seri, dönem veya ölçü belirtilmiyor. |
| Bankacılık düzeltme tahmini | 1 | Tahminin işlem günü ufku belirtilmiyor. |
| THYAO nakit değerlendirmesi ve banka hisseleri görüşü | 2 | Nitel görüş. Açık bir ölçüt veya sayısal eşik belirtilmiyor. |

İlk doğrulama denemesi için ENKAI girdisi hazır. Yayın saati sınırı uygulanarak mevcut `fundamentals.growth` hesabıyla %55,6643 tekrar üretildi. Diğer satırlardaki eksikler korunacak ve gerekçe olarak sunulacak. Bu ön inceleme, sayısal doğrulama kararı üretmedi. Tam test koşusunda 340 test geçti.

Üçüncü aşama tamamlandı. 181 segmentten 276 aday çıktı. Egemen'in 12 onayı `speech-2026-11-27-a021d36033` kaydıyla aktarıldı ve yayın günü sınırı doğrulandı. Dördüncü aşamada `analytics/claims.py` içinde birimi eşleştirilmiş gözlem için kapsayıcı aralık kontrolü ve seçili işlem günü başlangıcı için as_of tarihine kilitli ileri pencere eklendi. 28 odaklı test, Ruff ve mypy geçti.

Egemen dördüncü aşamaya başlamayı onayladı. 12 onaylı aday incelendi. ENKAI yıllık hasılat örneği, video yayımlanmadan önce açıklanan 1566104 numaralı KAP raporunun aynı konsolide tablosundaki 12 aylık cari ve önceki değerlerle tekrar hesaplandı. Gözlem %55,6643, söylenen %55. Tam yüzde için ±0,5 yüzde puanı uygulanırsa gözlem aralığın dışında kalır. Bu bir yöntem denemesidir. Diğer adaylarda özel skor tanımı, açık tahmin ufku, belirli metrik veya bağlam eksikliği görüldü.

Devam noktası, doğrulama metodolojisi ve araç sözleşmesi için Egemen'in açık onayını almak. Öneri, sayısal iddialarda söyleniş hassasiyetini esas almak, KAP ve makro bilgisini yayın anında kesmek, karşılaştırılabilir dönem veya açık tahmin ufku bulunmadığında gerekçeyi raporlamak ve mevcut `get_speech_features` çıktısını genişletmek. Yayın saatinin ileri işlem penceresine nasıl bağlanacağı ayrıca kesinleştirilecek.

Kodla seçilen 30 adaylık örneklem (tohum 42) Codex tarafından alıntı, çevre metni, konu ve iddia alanları üzerinden denetlendi. 2 doğru, 19 kısmen doğru, 9 yanlış. Katı kesinlik %6,7 (Wilson %95 GA %1,8–21,3), geniş kesinlik %70,0 (GA %52,1–83,3). Kısmi eşleşmelerde yön, metrik ve bağlam eksikleri görüldü. Yanlışlar arasında muhabir sorularının iddia sayılması ve şirket ifadesinin sektöre genellenmesi var. Denetim etiketleri `.assets/iddia-kesinlik-denetimi.json` içinde ve Egemen'in onaylarından ayrı tutuluyor.

Egemen üçüncü aşamaya geçişi onayladı. `bist-analist` ile 181 segmentin çıkarımı arka planda çalışıyor. `DURUM.cmd` işlenen segmentleri ve biriken inceleme adaylarını gösterir. Tamamlanan her segmentin girdisi, model kimliği, şeması ve çıkarım ayarlarıyla eşleşen sonuç, `.assets/speech-extraction.sqlite` dosyasından yeniden kullanılır. Geçersiz model yanıtı yeniden denenebilir kalır.

İlk denemede modelin serbest yazdığı konu adları ve alıntılar gereksiz retlere yol açtı. Üretim koşusunda model aday listesinden konuyu ve numaralı kaynak pasajını seçiyor. Kod alıntıyı doğrudan segmentten alır. İlk gerçek adayın kaynak içeriği ve kimliği doğrulandı, insan kararı bekliyor.

337 test, Ruff lint ve format ile mypy geçti. Testlerde bozulan çıkarımın tekrar denenebilmesi, değişen girdinin önbelleği geçersiz kılması, insan kararının korunması ve yalnız onaylı iddianın video yayın tarihi itibarıyla PIT okumasına girmesi denetlendi.

Beş Finans ve Borsa videosunun 50 segmenti tamamlandı. 54 adayın kayıt kimliği ve alıntısı gerçek segmentle doğrulandı. Numaralı insan inceleme listesi `.assets/fb-iddia-inceleme.txt` dosyasında. Numara sırası `.assets/fb-iddia-inceleme-indeks.txt` içinde iddia kimliğine bağlandı. TCMB ve Fed çıkarımı sürerken bu listedeki onaylar alınabilir. Belirtilmeyen iddialar beklemede kalır.

Egemen 06, 08, 09, 23, 24, 26, 30, 31, 33, 34, 41 ve 53 numaralı 12 adayı onayladı. Kararlar ilgili yerel JSONL dosyalarına kaydedilip yeniden okundu. Diğer 42 aday beklemede. Tam çıkarımdan sonra denetim örneklemi oluşturulacak ve onaylı iddialar dondurulacak.

Çıkarımı sürdürmek için etkin bir kopya olmadığını doğrula ve `.venv\Scripts\python.exe -m bistharness.harness.claims --as-of 2026-11-26` çalıştır. Arka plan günlüğü `.assets/speech-extraction.stderr.log` dosyasında. Kaynak alıntıları ve kararlar `data/manual/claims/<source_id>.jsonl` içinde yerelde kalır.

Tam koşu tamamlandıktan sonra insan incelemesinde yalnız `reviewed` (onay için `true`, ret için `false`, bekleyen için `null`), `review_note` ve örneklemde `audit` alanlarını düzenle. Örneklemi `.venv\Scripts\python.exe -m eval.speech_review_audit --list` ile listele. Örnek kayıtları `correct`, `partial` veya `incorrect` olarak değerlendir ve kesinlik ile Wilson aralığını aynı komutla ölç. Ardından onaylı dosyaları yeni bir snapshot adıyla `speech --include-reviews` yolundan ingest et ve PIT çıktısını doğrula. Finansal iddia doğrulaması dördüncü aşamanın ayrı onayını bekler.

`powershell -NoProfile -ExecutionPolicy Bypass -File setup\checkpoint.ps1` son güvenli kaydı gösterir. JSON doğrulaması başarısız olursa `git show HEAD:CHECKPOINT.json` ile son yerel Git kaydını oku ve dosya sağlama toplamlarını yeniden kontrol et. `powershell -NoProfile -ExecutionPolicy Bypass -File setup\resume_assets.ps1` Release DB ve modeli doğrular veya yarım indirmeye devam eder. `-SkipModel` ile yalnız DB hazırlanır. Kesinti sonrası etkin bir indirme varsa aynı işlemi ikinci kez başlatmadan önce durumu kontrol et.

Geçici ağ hatasında indirme artan beklemelerle toplam 12 denemeye kadar otomatik sürdürülür. Her deneme diskteki gerçek bayt sayısından başlar. Denemeler tükenirse kısmi dosya ve doğrulanmış parçalar korunur. Arka planda başlatılan model işinin kayıtları `.assets/model-resume.stdout.log` ve `.assets/model-resume.stderr.log` dosyalarında.

`powershell -NoProfile -ExecutionPolicy Bypass -File setup\resume_assets.ps1 -OllamaRuntime` sabit sürümün Windows paketini doğrulayıp `.tools/ollama-0.40.17` altına açar. WinGet bu sürümü listelemedi. Proje bağımlılıkları için `UV_CACHE_DIR=.tools/uv-cache` ve `UV_PYTHON_INSTALL_DIR=.tools/python` ortam değişkenlerini proje kökünü baz alarak ayarla. `uv sync --locked --python 3.12 --extra dev --extra llm --extra ui --extra mcp` komutuyla aynı ortamı sürdür.

Model ve çalışma zamanı doğrulandıktan sonra yerel Ollama hizmetinin mevcut durumunu denetle. Gerekirse `OLLAMA_HOST=127.0.0.1:11434` ve proje altındaki `.tools/ollama-models` yoluyla `OLLAMA_MODELS` ayarlayarak `.tools/ollama-0.40.17/ollama.exe serve` başlat. Release GGUF'u `setup/get_assets.ps1` içindeki Modelfile ayarlarıyla kaydet. Mevcut aynı adlı modelin kaynağını kontrol et. `ollama show bist-analist --modelfile` ve harness duman testiyle doğrula.

## Uzun işleri sürdürme

`CHECKPOINT.json` ortak durumun küçük bir özetidir. Gerçek dosya boyu ve SHA-256 kayıttan önce doğrulanır. Geçersiz kayıt veya yarım sonuç başarı sayılmaz. `in_progress` yeniden başlanabilir işi, `failed` son geçerli denemenin hatasını, `completed` doğrulanmış çıktıyı gösterir. Yarım Release dosyaları `.assets/` içinde SHA-256 kimlikli yollarında durur. Aynı varlık tekrar çağrıldığında HTTP Range destekleniyorsa aynı dosyadan devam edilir. Dosyanın tamamı Release SHA-256 ile karşılaştırılır. Kurulu DB ingest sonrası değişebileceği için farklı içerikli kurulu varlık için operatör kararı gerekir.

Speech çıkarımı uygulanırken segment kimliğini kaynak, zaman aralığı, yayım zamanı, metin ve etiketlerin kanonik hash'iyle oluştur. Yeniden kullanım ayrıca model digest'i, prompt, JSON şeması, çıkarım ayarları ve normalizasyon sürümü eşleşmesini gerektirir. Sonuç ve iş durumunu tek işlemde kalıcılaştır. Şema ve kaynak denetiminden geçmiş boş liste de tamamlanmış sonuçtur. Kesilmiş, hatalı veya onaysız sonuçlar kendi durumunda kalır. İnceleme durumunu sonuç hash'ine bağla. Değişen segment ve bağımlılıkları yeniden işle. Çıktı ve inceleme verisini Git dışında tut. Bu ayrıntılar çıkarım aşamasında test edilecek.
