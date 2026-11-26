# BIST Harness çalışma talimatları

- Uygulama değişikliğinden önce `README.md`, `CLAUDE.md` ve `docs/VIDEO_KATMANI_REHBERI.md` dosyalarını tamamen oku. Proje mimarisi, veri ve test kuralları için `CLAUDE.md` bağlayıcıdır.
- `feature/speech-layer` dalında çalış. `main` üzerinde değişiklik yapma. Egemen onaylamadan push veya merge yapma. Mevcut kullanıcı değişikliklerini koru.
- Araç girdisi, çıktısı veya araç listesi değişmeden önce Egemen'in açık onayını kaydet. Doğrulama metodolojisi, video listesi ve yeniden eğitimle ilgili rehberdeki karar noktalarını Egemen'e getir.
- Çıkarım yerel Ollama ile yapılır. Finansal hesaplar saf Python analitik katmanında yapılır. Bilgi tarihi kontrolleri SQL ve sonuç düzeyinde `PITRepository` üzerinden yürür. Yeni erişimleri gelecekteki satır testleriyle doğrula.
- Konuşmacı sayılarını kaynak metadatasında tut. Açıklama sayıları yalnızca doğrulanmış kanıtın `display` alanından gelir. YouTube'un sunduğu transkript panelini kullan.
- Git'e transkript, ham alıntı içeren iddia dosyası, ağırlık, veritabanı veya gizli bilgi ekleme. Her commit öncesi indeks içeriğini kontrol et. Kullanıcıya Türkçe yaz.

## Kaldığımız yerden devam et

1. `git status --short --branch`, `git diff`, `git diff --cached` ve `git log -5 --oneline` ile dalı, kullanıcı değişikliklerini ve son commit'leri kontrol et.
2. `PROJECT_CONTEXT.md`, `TASKS.md`, `PROGRESS.md` ve `CHECKPOINT.json` dosyalarını oku. Son güvenli durumu doğrulanmış çıktı ve gerçek Git durumu ile belirle. Yarım dosyaları, tamamlanmış kayıtları ve geçici dosyaları kontrol et.
3. İş kimliği veya çıktı hash'i değişmişse etkilenen girdiyi yeniden doğrula. Önceden insan onayı gerektiren noktalar için mevcut onayı kontrol et. Yalnız doğrulanmış fazdan ve `PROGRESS.md` üzerindeki sonraki adımdan devam et.
4. Her anlamlı adımda sonuç, doğrulama, engel ve sonraki adımı `PROGRESS.md` ve `TASKS.md` içine kaydet. Uzun işler için `setup/checkpoint.ps1` ile atomik kayıt yaz. Commit öncesi yalnız adı belirtilen proje dosyalarını stage et. Kullanıcının stage ettiği değişiklikler varsa ayrı tut. Küçük yerel checkpoint commit'leri kullan.
