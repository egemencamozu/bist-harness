# Video transkriptleri

Her video için `data/manual/videos.csv` satırındaki `source_id` ile aynı adlı dosya (`<source_id>.txt`).
Bu klasördeki `.txt` dosyaları git'e girmez (üçüncü taraf metni; ham haber metni gibi yerelde kalır).

## YouTube transkripti (tüm videolar)

1. Videoyu YouTube'da aç → açıklamanın altındaki **"Transkripti göster"** düğmesi.
2. Sağda açılan panelde zaman damgaları görünür olsun (⋮ menüsünde "Zaman damgasını aç/kapat").
3. Paneldeki metnin tamamını seç (ilk satırdan son satıra sürükle) → kopyala → `<source_id>.txt` içine yapıştır → kaydet.

Biçim önemli değil: `0:05` satırı + alttaki metin, ya da `0:05 metin` tek satırda — ikisi de okunur.
"5 saniye" gibi ekran okuyucu etiketleri ve panel başlığı atlanır.

## Resmi metin (yalnız TCMB ve Fed)

- `tcmb_20260813_er3.official.txt`: tcmb.gov.tr → Konuşmalar → 13.08.2026 "Enflasyon Raporu 2026-III" konuşma
  metni (PDF) → metni kopyala, yapıştır. Ayrıca TCMB YouTube kanalındaki videonun linkini `videos.csv`'deki boş
  `url` alanına yaz.
- `fed_20260729_presconf.official.txt`: https://www.federalreserve.gov/mediacenter/files/FOMCpresconf20260729.pdf
  → metni kopyala, yapıştır. Altyazı için Federal Reserve YouTube kanalındaki 29.07.2026 basın toplantısı videosu.

Resmi metin, YouTube altyazısının kelime hata oranını ölçmek için kullanılır (`speech.aligned_wer`).

## Sonra

```
uv run python -m bistharness.data.ingest speech --snapshot 2026-11-20
```
Transkript eklenip/değiştirilirse yeni bir snapshot tarihi gerekir (ör. `2026-11-21`; bu tarihten önce yayımlanan
videolar alınır); eski donmuş metin sessizce kullanılmaz.
