# Video Katmanı Devir Rehberi

Bu dosya, projeye video (konuşma) katmanını eklemek için gereken her şeyi tek yerde toplar. Sırasıyla oku:
önce projenin ne olduğunu ve şimdiye kadar ne yapıldığını (§1–§3), sonra kurulumu (§4), kuralları (§5) ve son olarak
asıl görevi (§6).

Projenin tüm kuralları ve tasarım kararları `CLAUDE.md` dosyasında. Bu rehber onun özeti ve senin görevine
odaklanmış hali. Çelişki olursa `CLAUDE.md` geçerlidir.

---

## 1. Proje 5 dakikada

**Ne yapıyor?** BIST hisseleri hakkında Türkçe sorulan bir soruyu alıyor, cevabı geçmiş veriyle **hesaplıyor ve
test ediyor**, sonra her sayısı kanıtlı bir Türkçe açıklama yazıyor. Yatırım tavsiyesi vermiyor. Sorduğu soru şu:
"Geçmiş veri bu iddiayı destekliyor mu?"

**Çekirdek ilke:** LLM yorumlar ve açıklar. Python araçları hesaplar. Harness kontrol eder. Backtest doğrular. Kanıt
loglanır. Son kararı insan verir.

**Örnek:** *"ASELS pazartesi düşerse cuma günü toparlıyor mu?"* (analiz tarihi 17.04.2026)
1. Model soruyu anlar: senaryo S2 (haftanın günü), hisse ASELS, örüntü "Pazartesi düşüş → Cuma".
2. Araçlar geçmişi tarihe göre böler: 2024–2025 örneklem içi, 2026 örneklem dışı.
3. Sonucu ölçer: 87 haftanın 35'inde pazartesi düşmüş. Bu haftalarda cumaların %45,71'i pozitif kapanmış.
   Çoklu test düzeltmesinden sonra p = 0,996.
4. Backtest maliyeti ekler: getiri yaklaşık sıfır.
5. Risk kapısı izin verilen eylemleri belirler. Model açıklamayı yazar, denetçi her sayının kanıtta olup olmadığını
   kontrol eder. Sonuç **REJECT_SIGNAL**: örüntü geçmişte desteklenmiyor.

**Neden önemli?** Model kendi başına bırakılınca sayı uyduruyor. Bunu ölçtük (§2). Sistemin değeri, modelin
söylediği her şeyin deterministik kodla doğrulanması.

**Ders:** CSE-481 Mühendislik Ekonomisi (Akdeniz Üni., Dr. Alper Özcan). Teslim 30 Kasım 2026, sunuma kadar
(~6 Aralık) uzayabilir. Aynı altyapı FinTreX (TÜBİTAK 2209-A / bitirme projesi: Türkçe finansal haber → 95 BIST
hissesinin ertesi gün yönü) için de kullanılacak.

---

## 2. Şimdiye kadar yapılanlar

| Faz | İçerik | Durum |
|---|---|---|
| 1 | Veri katmanı: fiyat (FinTreX price-scraper + yfinance), KAP bilançoları (XBRL), makro (TCMB, FRED), Bloomberg HT haber metadatası (96 hisse). Hepsi tarih kilitli (point-in-time) tek bir SQLite DB'de. | ✅ |
| 2 | Analitik: indikatörler (hocanın scriptleriyle birebir, parity testli), olay analizi, sektör göreli güç, haftanın günü, temel oranlar, makro ilişki. | ✅ |
| 3 | 15 MCP aracı + MCP sunucusu. Her araç `as_of_date` alıyor; her araç için "zehirli gelecek satırı" testi var. | ✅ |
| 4 | 17 adımlı harness: izin haritası, as_of kilidi, risk kapısı, çıktı denetçisi, episodik bellek, replay (tekrar üretim), Streamlit arayüzü. | ✅ |
| 5 | Kendi modelimiz **bist-analist**: Qwen3.5-4B, 10.596 örnekle QLoRA ince ayarı, GGUF Q8_0, Ollama. | ✅ |
| 6 | Ölçümler: golden, held-out, dayanıklılık, A–E ablasyonu, önce/sonra karşılaştırması. | ✅ |
| — | **Video katmanı** | 🟡 ilk adım hazır, gerisi sende (§6) |
| 7 | Raporlar ve sunum | ⏳ |

### Ana sonuçlar (hepsi `reports/` altında)

- **Golden (5 referans soru):** 5/5 geçti, hepsi ilk denemede. Model kuralların hesapladığı eylemle 5/5 aynı kararı
  verdi (`reports/golden_final.json`).
- **Taban model ile ince ayarlı model** (aynı kanıt paketleri, 20 soru; `reports/bakeoff_final/`):

  | | ilk denemede geçti | şablona düşmeden | uydurma sayı | yasaklı ifade | kurallarla aynı karar |
  |---|---|---|---|---|---|
  | qwen3.5:4b (taban) | %35 | %60 | %15 | %30 | %10 |
  | **bist-analist** | **%100** | **%100** | **%0** | **%0** | **%95** |

- **A–E ablasyonu** (aynı model, altyapı katman katman ekleniyor; `reports/ablation/`). Satırdaki oran "herhangi
  bir kural ihlali" yapılan soruların payı:

  | | A (yalnız model) | B (+araçlar) | C (+harness, kapı yok) | D (tam sistem) | E (+bellek/replay) |
  |---|---|---|---|---|---|
  | bist-analist | %50 | %5 | %10 | **%0** | **%0** |
  | qwen3.5:4b | %35 | %65 | %60 | **%0** | **%0** |

  Güvenliği harness sağlıyor, ince ayar ise sistemi kullanışlı yapıyor. Model tek başına (A) soruların %45'inde
  sayı uyduruyor.
- **Soru anlama** (30 yeni soru, eğitimden sonra yazıldı): kurallı ayrıştırıcı %30, taban model %73,
  bist-analist **%100** (`reports/robustness/v2/`).
- **Haber etiketleme kesinliği** (elle denetim, 2 tur): %90 (`reports/news_tagging_audit.md`).

---

## 3. Mimari harita

```
config/       universe.yaml · settings.yaml · news.yaml (haber/hisse etiketleme) · harness_policy.yaml (iş akışı, izinler)
data/         db/bist.sqlite (git'e girmez, release'den gelir) · raw/<kaynak>/<snapshot>/ (donmuş ham veri + sha256)
              manual/videos.csv + manual/transcripts/ (SENİN alanın)
src/bistharness/
  core/       enums · schemas · pit.py (PITRepository: tüm okumalar buradan, as_of kilidi) · formatting
  data/       db.py (tablolar) · ingest/ (prices, kap, macro, news, speech ← senin dosyan)
  analytics/  saf hesap fonksiyonları, IO yok
  backtest/   motor + stratejiler
  tools/      15 araç (context.py içinde get_speech_features ← senin aracın)
  harness/    runner (17 state) · planner · validator · risk_gate · memory · replay · llm_client (Ollama) · intent
  ui/         Streamlit
eval/         golden, held-out, ablasyon, bakeoff, dayanıklılık
training/     veri üretimi + QLoRA + GGUF dışa aktarma
tests/        ~330 test
```

**Katman yönü tek yönlü:** `core ← data ← analytics ← backtest ← tools ← harness ← ui`. Alt katman üst katmanı
import edemez; bunu `tests/test_architecture.py` her test koşusunda kontrol ediyor. Örneğin `data/ingest/speech.py`
LLM istemcisini (harness) import edemez.

**17 state:** START → … → LOAD_NEWS_AND_SPEECH_CONTEXT (burada `get_news_events` ve `get_speech_features`
çağrılabilir) → BUILD_EVIDENCE → … → RUN_BACKTEST → RISK_GATE → GENERATE_EXPLANATION → HUMAN_REVIEW → LOG_AND_CLOSE.

---

## 4. Kurulum (macOS veya Windows)

Komutlar iki sistem için ayrı verildi. **macOS** ana yol, Windows komutları altında.

### 4.1 Gerekenler
| Araç | macOS | Windows | Not |
|---|---|---|---|
| Git | `xcode-select --install` (ya da `brew install git`) | git-scm.com | |
| [uv](https://docs.astral.sh/uv/) | `brew install uv` | `winget install astral-sh.uv` | Python 3.12'yi kendisi kurar |
| [Ollama](https://ollama.com/download) | uygulamayı indir | kurulum dosyası | **0.40.17** önerilir (sonuçlar bu sürümle ölçüldü) |
| GitHub CLI | `brew install gh` | `winget install GitHub.cli` | sonra `gh auth login` |

- **Donanım:** Apple Silicon (M1–M4) Mac'te Ollama GPU'yu (Metal) kendisi kullanır. Model 4,5 GB olduğu için en az
  16 GB RAM rahat çalışır. Windows'ta ≥ 6 GB VRAM'li bir NVIDIA GPU önerilir.
- **Mac'te çıktı farkı:** ölçümler Windows + NVIDIA'da yapıldı. Mac'te (Metal) model aynı soruya bayt düzeyinde
  biraz farklı cevap üretebilir. Bu normaldir, denetçi ve testler bundan etkilenmez. `reports/` altındaki sayıları
  yeniden üretmeye çalışma; tekrar üretim (replay) karşılaştırmalarını hep aynı makinede yap.
- Ollama yeniden başlarken yarım inmiş modelleri silmesin diye: macOS'ta `launchctl setenv OLLAMA_NOPRUNE 1`,
  Windows'ta `setx OLLAMA_NOPRUNE 1`.

### 4.2 Projeyi al
Depo gizli. Egemen seni collaborator olarak ekledi; GitHub'dan gelen daveti kabul et.
```bash
gh auth login                      # GitHub.com → HTTPS → Login with a web browser
gh repo clone egemencamozu/bist-harness
cd bist-harness
git checkout feature/speech-layer
uv sync --extra dev --extra llm --extra ui --extra mcp
```

### 4.3 Veritabanı ve model
İkisi de git'te değil; depodaki gizli **GitHub Release**'te (`assets-2026-11-20`) duruyor. Betik indirir,
sha256'ları doğrular, yerlerine koyar ve modeli Ollama'ya kaydeder. Önce Ollama'nın açık olduğundan emin ol.
```bash
bash setup/get_assets.sh                    # macOS: DB (~15 MB) + model (~4,5 GB)
bash setup/get_assets.sh --skip-model       # yalnız DB
```
```powershell
powershell -ExecutionPolicy Bypass -File setup\get_assets.ps1             # Windows
powershell -ExecutionPolicy Bypass -File setup\get_assets.ps1 -SkipModel  # yalnız DB
```
- Beklenen çıktı: her dosya için `ok ...` satırları, sonunda `ollama list` içinde `bist-analist`.
- Dosyalar şuraya gider: `data/db/bist.sqlite` ve `models/bist-4b-q8_0.gguf`.
- İş bitince `.assets/` klasörünü silebilirsin.

İddia çıkarmada taban modeli de denemek istersen: `ollama pull qwen3.5:4b`.

### 4.4 Çalıştığını doğrula
```bash
uv run pytest -q                 # hepsi geçmeli (DB varsa ~334 test)
uv run ruff check . && uv run mypy src
uv run python -m bistharness.harness run --as-of 2026-09-10 --explainer llm --question "ASELS pazartesi düşerse cuma toparlıyor mu?"
uv run streamlit run src/bistharness/ui/app.py   # http://localhost:8501
```
Harness komutu 17 state'in durumunu, kanıtları, kapıyı ve modelin açıklamasını basar (~30–60 sn).

**Docker:** Mac'te Docker container'ları GPU'ya erişemez, yani model container içinde CPU'da ve çok yavaş çalışır.
Mac'te yerel kurulumu (yukarıdaki adımlar) kullan.

---

## 5. Kurallar (ihlal edilemez)

Tam liste `CLAUDE.md` §1–§4'te. Video katmanı için en önemlileri:

1. **İnternet yalnızca `bistharness.data.ingest` içinde.** Analiz, harness, UI ve eval hep donmuş veriden okur.
   Bulut LLM yok (OpenAI, Anthropic, Gemini…); yalnızca yerel Ollama.
2. **LLM sayı üretmez.** Açıklamadaki her sayı bir aracın `display` değerinden birebir kopyalanır. **Videodaki bir
   sayı, bizim aracımız doğrulamadan kanıta giremez.** Konuşmacının "net kâr %40 arttı" demesi bir *iddia*; kanıt,
   bizim KAP verimizden hesaplanan değer.
3. **as_of kilidi.** Bir video `published_at` anından önce bilinemez. Doğrulama da yalnızca `as_of` tarihine kadar
   bilinen veriyi kullanır. Her yeni okuma `PITRepository` üzerinden yapılır ve her araç için "zehirli gelecek satırı"
   testi zorunlu.
4. **Eksik pencere sessizce atılmaz.** "Sonraki 20 günde" diye bir iddia varsa ve as_of'a kadar 20 işlem günü
   geçmemişse, iddia `FORWARD_WINDOW_INCOMPLETE` ile raporlanır.
5. **Yatırım tavsiyesi yok.** "Al", "hedef fiyat", "kesin yükselir" gibi ifadeler sistemin ürettiği metinde geçemez.
   Konuşmacının sözlerini alıntılamak serbest, ama alıntı açıklama metnine değil kanıt meta verisine girer.
6. **Platform korumaları aşılmaz.** YouTube'dan `yt-dlp` vb. ile indirme **yok**. Metin, YouTube'un kendi
   "Transkripti göster" panelinden elle kopyalanır.
7. **Transkriptler git'e girmez** (üçüncü taraf metni). `.gitignore` bunu zaten sağlıyor.
8. **Araç imzası değişikliği onay ister.** 15 aracın girdi/çıktısını değiştirmeden ya da yeni araç eklemeden önce
   Egemen'e sor (§6.5).
9. Kod, tanımlayıcılar ve yorumlar İngilizce; kullanıcıya dönük metin Türkçe. Her dosya IO'sunda `encoding="utf-8"`.
   Proje yolunda Türkçe karakter ve boşluk var, yolu asla elle yazma. Kütüphane kodunda `print` yok.

---

## 6. Görev: video katmanı

### 6.1 Amaç
Şartname §16 "uzman görüşünü" bağlam olarak istiyor. Konuşmalar yazıya dökülecek; konu, iddia, duruş ve belirsizlik
çıkarılacak. **Sayısal iddialar deterministik araçlarla doğrulanmadan kanıta girmeyecek.** Uzman görüşü doğru kabul
edilmiyor.

Sunumda göstermek istediğimiz şey:
> *"Mete Üstündağ 05.03.2026'daki videosunda (03:10–04:05) THYAO'nun net kârının X arttığını söyledi (E7). KAP
> verimize göre artış %Y (E3): iddia doğrulanıyor. Aynı videoda 'yabancı alımı sürüyor' dedi: bu iddia elimizdeki
> veriyle doğrulanamıyor (E8)."*

### 6.2 Hazır olanlar
- **`data/manual/videos.csv`**: deneylerden **önce** sabitlenen 7 video. Listeyi değiştirme; değişiklik gerekiyorsa
  önce Egemen'le konuş.

  | source_id | Video | Yayım (TR) | Ne sınanır |
  |---|---|---|---|
  | `fb_20260305_bilanco` | [Yeni Gelen Bilançoların Analizi (THYAO, ENKAI, SAHOL, TTKOM, MGROS, CCOLA, DOHOL)](https://www.youtube.com/watch?v=sDjF5fatrw0) | 05.03.2026 19:31 | Bilanço rakamları → KAP verisiyle **doğrulanabilir** |
  | `fb_20260307_savas` | [Savaş Devam Ederse Hangi Sektörler Pozitif Ayrışır?](https://www.youtube.com/watch?v=g7EGrVfp9q4) | 07.03.2026 12:00 | Sektör iddiası → sonraki göreli performans (**ileriye dönük**) |
  | `fb_20260121_paragirisi` | [Borsada Para Girişi Yoğun Olan Hisseler](https://www.youtube.com/watch?v=ZF2Hdf4C9ak) | 21.01.2026 07:00 | Para girişi verisi yok, hacim var → **kısmen** |
  | `fb_20260306_yabanci` | [Yabancı Borsada Alıma Devam Ediyor!](https://www.youtube.com/watch?v=9XbhNMFLwaI) | 06.03.2026 08:42 | Yabancı akış verisi yok → **doğrulanamaz** |
  | `fb_20260305_bofa` | [BofA Bir Hisse 2,5 Milyar TL Alım Yaptı](https://www.youtube.com/watch?v=q7fdjzhmAcU) | 05.03.2026 08:19 | Aracı kurum verisi yok → **doğrulanamaz**; sonraki fiyat ölçülebilir |
  | `tcmb_20260813_er3` | TCMB Karahan, Enflasyon Raporu 2026-III (URL'yi sen dolduracaksın) | 13.08.2026 11:30 | Enflasyon/faiz → `TUFE_YOY`, `TCMB_POLICY_RATE`; resmi metin altyazı kalitesini ölçer |
  | `fed_20260729_presconf` | FOMC basın toplantısı, Kevin Warsh | 29.07.2026 22:30 | Faiz kararı → `FED_TARGET_*`; resmi transkript altyazı kalitesini ölçer |

  Konuşmacı ve kanal bilgisi videoların YouTube sayfasından alındı. Yayım zamanı Türkiye saatine çevrildi; canlı
  yayınlarda bilgi zamanı muhafazakâr olarak **yayının bitişi** alındı.

- **`src/bistharness/data/ingest/speech.py`** (docstring'i tek doğruluk kaynağı):
  - `parse_transcript`: YouTube panel metnini zaman damgalı parçalara ayırır ("5 saniye" gibi ekran okuyucu
    etiketlerini atlar; zaman geriye giderse hata verir).
  - `segment_cues`: parçaları ~60 saniyelik segmentlere toplar.
  - Hisse etiketleme `config/news.yaml` ile yapılır, haber etiketleyicisiyle aynı istisnalar geçerli.
  - `aligned_wer`: resmi metinle karşılaştırıp altyazının kelime hata oranını ölçer. FB videoları TCMB'de ölçülen
    kaliteyi ödünç alır, çünkü sistem ve dil aynı.
  - `run`: girdileri `data/raw/speech/<snapshot>/` altına sha256'lı olarak dondurur ve `speech_segments` tablosunu
    yeniden kurar.
- **`get_speech_features`** aracı (`tools/context.py`): `source_id` ya da konu/hisse koduyla segmentleri döndürür.
  Kalite < 0,6 olunca `LOW_TRANSCRIPT_QUALITY` uyarısı verir; şu an iddia doğrulaması yapmıyor.
- **Testler:** `tests/test_speech_ingest.py` (ayrıştırma, segmentler, WER, uçtan uca ingest, tarih kilidi,
  snapshot değişikliği).

### 6.3 Adım 1: transkriptleri yapıştır
Ayrıntılar `data/manual/transcripts/README.md` dosyasında. Kısaca:
1. Videoyu YouTube'da aç → açıklamanın altında **"Transkripti göster"**.
2. Panelde zaman damgaları açık olsun.
3. Metnin tamamını seç, kopyala ve `data/manual/transcripts/<source_id>.txt` dosyasına yapıştır.
4. **TCMB ve Fed için:**
   - YouTube altyazısını `<id>.txt` dosyasına, kurumun resmi metnini `<id>.official.txt` dosyasına yapıştır.
   - Fed metni: https://www.federalreserve.gov/mediacenter/files/FOMCpresconf20260729.pdf
   - TCMB metni: tcmb.gov.tr → Konuşmalar → 13.08.2026.
   - TCMB videosunun YouTube linkini `videos.csv` dosyasındaki boş `url` alanına yaz.
   - Fed satırındaki `url` şu an Fed'in sayfasını gösteriyor; YouTube linkini bulursan onunla değiştir.

### 6.4 Adım 2: ingest
```powershell
uv run python -m bistharness.data.ingest speech --snapshot 2026-11-20
```
- Beklenen çıktı: her video için `N segments, quality %…, tickers [...]`. Transkripti olmayan video için
  `TRANSCRIPT_MISSING` yazar.
- Snapshot bir kez dondurulduktan sonra transkript ekler ya da değiştirirsen aynı snapshot adı **hata verir**. Bu
  bilinçli: sonuçlar sessizce farklı bir metinle hesaplanmasın. Yeni tarih kullan: `--snapshot 2026-11-21`.
- Kontrol: hisse etiketleri doğru mu? "Türk Hava Yolları" geçen segment THYAO almalı. Yanlış etiket varsa
  `config/news.yaml` dosyasındaki `exclude` mekanizmasını kullan ve haber testlerinin de geçtiğinden emin ol.

```powershell
uv run python -c "import sqlite3; c=sqlite3.connect('data/db/bist.sqlite'); [print(r) for r in c.execute('select source_id, segment_start, topics, quality from speech_segments limit 20')]"
```

### 6.5 Adım 3: iddia çıkarma (önerilen tasarım)
**İlke: model önerir, kod doğrular, insan onaylar.**

1. **Çıkarma** (yeni modül, önerim `src/bistharness/harness/claims.py`; harness katmanında olmalı, çünkü LLM
   istemcisi orada):
   - Her segment için yerel model (`bist-analist` ya da `qwen3.5:4b`) bir **JSON şemasıyla** çağrılır.
   - Ayarlar diğer çağrılarla aynı: `harness/llm_client.py::OllamaClient`, temperature 0, seed 42, soğuk çağrı.
     Örnek kullanım için `harness/intent.py` ve `harness/explainer.py` dosyalarına bak.
   - Şemada `maxItems` / `maxLength` olmalı. Ollama gramerle uygular, ama 2.000 karakterin üstünü sessizce yok
     sayıyor (ölçüldü).
   - Önerilen iddia alanları:
     ```json
     {"claims": [{
        "subject": "THYAO",                     // hisse kodu | sektör adı | "MACRO"
        "claim_type": "fundamental_value",      // aşağıdaki listeden
        "quote": "net kârını yüzde 40 artırdı", // segment metninden BİREBİR alıntı
        "metric": "net_income",                 // fundamental_value / macro_value için
        "direction": "up",                      // up | down | none
        "horizon_days": null,                   // ileriye dönük iddialarda 1/5/20…
        "stance": "positive",                   // positive | negative | neutral
        "certainty": "high"                     // high ("kesin", "hep") | medium | low ("olabilir")
     }]}
     ```
     `claim_type` ∈ {`fundamental_value`, `price_move_past`, `price_move_forecast`, `sector_relative_forecast`,
     `volume_flow`, `foreign_or_broker_flow`, `macro_value`, `opinion`}.
2. **Kod doğrulaması** (çıkarma sonrası, deterministik; geçmeyen iddia atılır ve sayılır):
   - `quote`, segment metninin birebir alt dizgisi olmalı (Türkçe küçük harf karşılaştırması).
   - Alıntıdaki her sayı `quote` içinde geçmeli; model sayı uyduramaz. Altyazı sayıları "yüzde 40" ya da "%40" diye
     yazabilir; ikisini de ayrıştır. `core/formatting.py::numbers_in` iyi bir başlangıç ama "yüzde 40" biçimini
     muhtemelen eklemen gerekecek.
   - `subject` bir hisse ise, segmentin etiketlerinde (tagger) olmalı ya da adı alıntıda geçmeli.
     `harness/intent.py::ground_tickers` aynı mantığı soru için yapıyor.
3. **İnsan onayı (HITL):** çıkarılan iddialar `data/manual/claims/<source_id>.jsonl` dosyasına yazılır. Bir tur elle
   gözden geçirilir; her iddiaya `reviewed: true/false` ve gerekirse not eklenir. Onaylanan dosya donmuş girdi olur ve
   `data.ingest speech` onu yeni bir `speech_claims` tablosuna alır. Bilgi zamanı = videonun `published_at` anı.
   Tabloyu `data/db.py` dosyasına ekle, okumayı `PITRepository`'ye yeni bir metot olarak yaz.
4. **Kesinlik ölçümü:** haber etiketlemede yaptığımız gibi (`reports/news_tagging_audit.md`). Rastgele bir örnek
   al, elle "doğru / kısmen / yanlış" diye işaretle ve Wilson güven aralığıyla raporla.

### 6.6 Adım 4: doğrulama (önerilen tasarım, **önce Egemen'e sor**)
İddia türünü mevcut araçlara ve analytics fonksiyonlarına eşle:

| claim_type | Doğrulama | Hangi veri |
|---|---|---|
| `fundamental_value` | Söylenen değer/değişim, KAP raporundaki değerle uyumlu mu? Tolerans = söyleniş hassasiyeti ("12 milyar" → 11,5–12,5). | `calculate_fundamental_change` / `get_fundamental_metrics`, **as_of = yayım günü** |
| `price_move_past` | "Son 1 ayda %20 yükseldi" doğru mu? | `get_stock_history` |
| `price_move_forecast`, `sector_relative_forecast` | Yayımdan sonraki h işlem gününde gerçekleşti mi? Hisseyi XU100'e ve akran sepetine göre ölç. | fiyat + `rank_sector_relative_strength`; as_of < yayım + h → `FORWARD_WINDOW_INCOMPLETE` |
| `volume_flow` | Hacim gerçekten arttı mı (hacim z-skoru)? Para girişinin kendisi ölçülemez → **kısmen**. | `calculate_indicators` |
| `macro_value` | TÜFE / politika faizi / Fed aralığı söylenenle aynı mı? | `get_macro_context` |
| `foreign_or_broker_flow` | Verimiz yok → `NOT_VERIFIABLE` | — |
| `opinion` | Doğrulanmaz, yalnızca bağlam | — |

Sonuç kümesi: `SUPPORTED`, `CONTRADICTED`, `PARTIAL`, `NOT_VERIFIABLE`, `FORWARD_WINDOW_INCOMPLETE`. Kanıt
cümlesindeki her sayı **bizim hesapladığımız** değerden gelir. Konuşmacının sayısı ayrı bir meta alanda tutulur ve
`display` alanına girmez. Bu, testli bir değişmez (`tests/test_tools.py`).

**Nerede çalışmalı?** İki seçenek var. İkisi de araç sözleşmesini değiştirdiği için **Egemen'in onayı gerekli**:
- **(Önerilen)** `get_speech_features` çıktısını genişlet: segmentlerle birlikte iddiaları ve `as_of` anındaki
  doğrulama sonucunu döndürsün. Araç sayısı 15 kalır, şartnamedeki araç listesi değişmez.
- Yeni bir 16. araç: `verify_speech_claims`. Bu durumda `harness_policy.yaml` izinleri, planlayıcı şeması ve
  `CLAUDE.md` §6 da güncellenmeli.

Doğrulama hesapları saf fonksiyonlar olarak `analytics/` altına gitmeli (ör. `analytics/claims.py`). IO yok;
her biri için unit test ve PIT zehir testi zorunlu.

### 6.7 Adım 5: harness ve arayüz entegrasyonu
- `harness/planner.py::ScenarioPlanner` şu an LOAD_NEWS_AND_SPEECH_CONTEXT state'inde yalnızca `get_news_events`
  çağırıyor (satır ~138). Hissenin geçtiği konuşma segmentleri için `get_speech_features` çağrısını ekle.
- Kanıt seçimi `config/harness_policy.yaml` içindeki `evidence:` glob'larıyla yapılıyor; konuşma kanıtları için
  (ör. `speech.*`) senaryolara ekle.
- Risk kapısı: düşük transkript kalitesi zaten bir uyarı (`tools/quality.py`).
- **Not:** bist-analist eğitim verisinde konuşma kanıtı yoktu. Açıklamada bu kanıtları nasıl kullandığını ölç;
  denetçi güvenliği yine sağlar. Gerekirse yeniden eğitim ayrı bir karar konusu.
- İsteğe bağlı: arayüzde (`ui/app.py`) bir "Video iddiaları" sekmesi; video, dakika, iddia ve sonuç tablosu ile
  YouTube'a dakikalı link (`&t=190s`).

### 6.8 Adım 6: değerlendirme ve rapor
- Bir eval betiği, örneğin `eval/speech_claims.py`: 7 videonun bütün iddialarını, türünü, sonucunu ve kanıtını bir
  tabloya döksün → `reports/speech_claims.md`.
- Raporda bulunması gerekenler:
  - Altyazı kalitesi (TCMB ve Fed WER)
  - İddia çıkarma kesinliği (elle denetim)
  - Sonuç dağılımı (kaç iddia doğrulandı / çelişti / doğrulanamadı)
  - 2–3 somut örnek
- Sunum için en iyi örnekler: V1 (bilanço sayıları doğrulanıyor), V2 (ileriye dönük sektör iddiası gerçekleşti mi),
  V4/V5 (doğrulanamayan iddia).

### 6.9 Bitti tanımı
- [ ] 5 FB transkripti (+ istersen TCMB ve Fed) yapıştırıldı, ingest çalıştı ve etiketler kontrol edildi.
- [ ] İddia çıkarma: şema + kod doğrulaması + elle onaylanmış `claims` dosyaları + kesinlik ölçümü.
- [ ] Doğrulama: claim_type eşlemesi, `analytics/` saf fonksiyonları, PIT zehir testleri.
- [ ] Araç/harness entegrasyonu (Egemen'in onayladığı seçenekle) ve en az bir uçtan uca harness koşusu.
- [ ] `reports/speech_claims.md` + 2–3 örnek.
- [ ] `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .` ve `uv run mypy src` temiz.
- [ ] `CLAUDE.md` §14'e kısa bir karar/sonuç notu eklendi.

---

## 7. Git iş akışı
- `feature/speech-layer` branch'inde çalış. `main` doğrudan değiştirilmez.
- Küçük ve anlamlı commit'ler at; mesajlar İngilizce olsun, ör. `speech: parse YouTube transcript panel`.
- Push → GitHub'da `main`'e Pull Request aç → Egemen inceler ve birleştirir.
- **Asla commit etme:** `data/db/*.sqlite`, `models/`, `*.gguf`, `data/manual/transcripts/*.txt`, `.assets/`,
  `.env`. `.gitignore` bunları zaten dışarıda tutuyor, yine de `git status` ile kontrol et.
- DB'yi yeniden kurman gerekirse (ör. yeni bir tablo eklediysen), tablo kodla oluşturulmalı (`data/db.py`) ve ingest
  komutuyla dolmalı. DB dosyasının kendisi paylaşılmaz.

## 8. Claude Code (ya da başka bir yapay zekâ asistanı) ile çalışıyorsan
- Claude Code proje kökündeki `CLAUDE.md` dosyasını otomatik okur; kurallar orada.
- İlk mesajda bu dosyayı göster: *"docs/VIDEO_KATMANI_REHBERI.md'deki görevi yapıyoruz, §6.3'ten başla."*
- Asistan araç imzasını değiştirmek isterse önce Egemen'e sor (§5 madde 8).
- Bulut LLM'i **kodun içinde** kullanmak yasak (§5 madde 1). Asistanla kod yazmak serbest; yasak olan, sistemin
  çalışırken bulut LLM'e istek atması.

## 9. Sık sorunlar
| Sorun | Çözüm |
|---|---|
| `UnicodeEncodeError` / bozuk Türkçe (Windows) | PowerShell'de `$env:PYTHONIOENCODING="utf-8"`; dosya IO'sunda her zaman `encoding="utf-8"` (kod iki sistemde de çalışmalı) |
| Model çok yavaş (dakikalar) | `num_ctx 4096` dışına çıkma (8 GB VRAM'de 8192 modeli CPU'ya taşıyor); Mac'te başka büyük uygulamaları kapat |
| Aynı istem farklı çıktı | Ollama önek önbelleği; harness "soğuk çağrı" yapıyor (`fresh: true`), sen de öyle yap |
| `prediction aborted, token repeat limit` | Model döngüye girmiş; `OllamaClient` bunu boş/geçersiz cevaba çevirir. Şemaya `maxItems`/`maxLength` ekle |
| `SnapshotIntegrityError ... use a new --snapshot` | Transkript değişti; yeni snapshot tarihi kullan (§6.4) |
| `gh release download` 404 | `gh auth login` yapılmamış ya da depoya erişimin yok |
| Testlerin bir kısmı "skipped" | `data/db/bist.sqlite` yok; §4.3'ü çalıştır |

## 10. Kime ne sorulur
- **Egemen:** araç imzası / yeni araç, video listesinde değişiklik, kapsam, yeniden eğitim, `main`'e birleştirme.
- **Kod hakkında:** her modülün docstring'i o modülün tek doğruluk kaynağı. Önce oraya bak.
