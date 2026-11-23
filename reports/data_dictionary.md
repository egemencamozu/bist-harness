# Veri Sözlüğü — `data/db/bist.sqlite` (snapshot 2026-11-20)

Tüm zamansal tablolar tek bir **bilgi zamanı** kolonu taşır; bütün okumalar `core/pit.py::PITRepository` üzerinden
`<bilgi kolonu> <= as_of` (as_of = o günün kapanışı sonrası, `YYYY-MM-DD 23:59:59`) filtresiyle yapılır ve dönüşte
yeniden doğrulanır (`LookAheadError`). Saatler Europe/Istanbul yerel saatidir. Snapshot `D` yalnızca `D`'den önce
tamamlanmış/yayımlanmış veriyi içerir. Ham kaynaklar `data/raw/<kaynak>/<D>/` altında sha256 manifest'le dondurulur.

| Tablo | Bilgi zamanı | Kaynak | Satır | Ingest komutu |
|---|---|---|---|---|
| `prices_daily` | `date` (kapanış) | FinTreX price-scraper (birincil) + yfinance (tamamlayıcı) | 96.213 | `ingest prices` |
| `corporate_actions` | `ex_date` | price-scraper `adj_factor` (bedelsiz/bölünme) + yfinance (temettü) | 312 | `ingest prices` |
| `price_quality_flags` | `date` (NULL = tarihsiz) | fiyat mutabakatı + kalite kontrolleri | 1.071 | `ingest prices` |
| `trading_calendar` | `date` | price-scraper çoğunluk takvimi + XU100 | 992 | `ingest prices` |
| `fundamentals` | `disclosure_datetime` | KAP XBRL "Finansal Rapor" (kapdata dökümü) | 119.969 | `ingest fundamentals` |
| `fundamental_issues` | `disclosure_datetime` | temel ingest uyarıları | 16 | `ingest fundamentals` |
| `macro_observations` | `release_datetime` | TCMB (kur, politika faizi, TÜFE tablosu), FRED | 2.624 | `ingest macro` |
| `news_events` | `published_at` (muhafazakâr) | Bloomberg HT arşivi (yalnız metadata) | 40.780 | `ingest news` |
| `speech_segments` | `published_at` | (konuşma katmanı, sonraki faz) | 0 | — |
| `instruments`, `universe_membership` | — (statik) | `config/universe.yaml` | 97 / 126 | `ingest prices` |
| `ingest_log`, `meta` | — | her ingest'in kimliği, `data_version`, kapsam sonları | — | tümü |

## prices_daily
| Kolon | Açıklama |
|---|---|
| `ticker`, `date` | anahtar; yalnızca doğrulanmış BIST işlem günleri |
| `open`, `high`, `low`, `close` | o gün **basılan** (ham) fiyatlar, TL |
| `volume` | basılan hisse adedi (price-scraper; değilse yfinance ciro korumalı) |
| `cum_factor` | kümülatif düzeltme faktörü (bölünme/bedelsiz × temettü); son gün = 1 |
| `price_source` | `price_scraper` / `yfinance` / `price_scraper_raw` (günün seviyesi hangi kaynaktan) |
| `factor_source` | faktörün kaynağı |

Okuma (`PITRepository.prices`): `adj_t = raw_t · cum_factor_t / cum_factor_asof` — **as_of'a çapalı**, böylece as_of
sonrasındaki kurumsal işlemler hiçbir çıktıyı değiştirmez; getiriler temettü dahil (hocanın `auto_adjust=True` tanımı).
Hacim ciro korumalı ölçeklenir. Ham kolonlar `raw_*` olarak da döner.

## fundamentals (rapor-merkezli uzun format)
| Kolon | Açıklama |
|---|---|
| `fiscal_period` | değerin ait olduğu mali çeyrek (şirket mali takvimi; MAVI'de mali yıl Ocak'ta biter) |
| `period_start`, `period_end`, `duration` | akımlar: `3M` çeyrek / `6M`,`9M`,`12M` yılbaşından kümülatif (KAP gibi); bilanço: `instant` |
| `report_period`, `disclosure_index` | değeri yayımlayan rapor ve KAP bildirim no (`kap.org.tr/tr/Bildirim/<no>`) |
| `role` | `current` = kendi raporundaki değer; `prior` = sonraki raporun karşılaştırmalı kolonu |
| `scope` | `consolidated` / `solo` |
| `statement`, `metric` | `balance`/`income`/`cashflow`; kanonik metrik adı (`config/fundamentals.yaml`) |
| `value`, `unit` | TL'ye normalize edilmiş değer (gider kalemleri negatif) |
| `tms29_adjusted` | rapor enflasyon muhasebesine göre yeniden ifade edilmiş mi (veriden tespit) |
| `source_ref` | `kap:<bildirim>#<XBRL kalem(ler)i>` — kanıt izlenebilirliği |

PIT okuma varsayılanı `role="current"`: her değer ilk yayımlandığı haliyle (+ o raporun KAP düzeltmeleri, ayrı
sürüm). TMS 29 ile yeniden ifade edilmiş karşılaştırmalar `role=None` ile görülür. Oranlar (F/K, PD/DD, marjlar,
net borç) burada saklanmaz; analitik katmanda as_of fiyatı × as_of'ta bilinen bilanço ile hesaplanır.

Formatlar ve metrikler (`config/fundamentals.yaml`):
- `tfrs` (sanayi/holding/GYO/aracı kurum): revenue, cost_of_sales, gross_profit, marketing/admin/rnd_expense,
  other_operating_income/expense, operating_profit, finance_income/costs, net_monetary_position, profit_before_tax,
  tax_expense, net_income, net_income_parent, depreciation_amortization, operating_cash_flow, capex, dividends_paid,
  total_assets, current/noncurrent_assets, cash, trade_receivables, inventories, current/noncurrent_liabilities,
  total_liabilities, total_equity, equity_parent, issued_capital, financial_debt.
- `bank` (BDDK): interest_income/expense, net_interest_income, net_fee_commission_income, trading_income,
  gross_operating_profit, expected_credit_losses, personnel_expense, other_operating_expense, operating_profit,
  net_income(_parent), total_assets, cash, loans, deposits, total_equity, issued_capital.
- `insurance` (SEDDK): gross_written_premiums, technical_balance, investment_income, profit_before_tax,
  net_income(_parent), operating_cash_flow, total_assets, current_assets/liabilities, cash, total_equity, issued_capital.

Bilinen durumlar: TRALT için KAP verisi yok; YKBNK `issued_capital` banka kolon onarımını geçemiyor (16 uyarı);
kapsam sonu `meta.fundamentals_coverage_end` = 2026-10-02 19:56:09 (2026Ç3 raporları yok).

## macro_observations
| `series_code` | Birim | Kaynak | `release_datetime` kuralı |
|---|---|---|---|
| `USDTRY`, `EURTRY` | TL | TCMB gösterge döviz alış kuru (günlük XML) | bülten günü 15:30 |
| `TCMB_POLICY_RATE` | % | TCMB 1 hafta repo tablosu (yürürlük tarihli) | yürürlük günü 00:00 (≤1 gün muhafazakâr) |
| `FED_TARGET_UPPER`, `FED_TARGET_LOWER` | % | FRED DFEDTARU / DFEDTARL (yalnız değişim noktaları) | yürürlük günü 00:00 |
| `TUFE_YOY`, `TUFE_MOM` | % | TÜİK TÜFE (TCMB tablosu), `obs_date` = ayın ilk günü | sonraki ayın 3'ü veya sonraki ilk işlem günü 10:00 |

Seviye serileri (politika faizi, Fed) basamak fonksiyonudur: t anındaki değer = `release_datetime <= t` olan son gözlem.

## news_events (yalnız metadata, metin yok)
| Kolon | Açıklama |
|---|---|
| `published_at` | **bilgi zamanı** = max(ilk yayın, son düzenleme): arşivdeki metin sonradan düzenlenmiş olabilir |
| `first_published_at` | ilk yayın zamanı (yalnız gösterim) |
| `title`, `url`, `source` | başlık, kaynak bağlantısı (`bloomberght`) |
| `tickers` | JSON liste; başlıkta alias, gövdede kod ya da ≥2 alias geçişi (`config/news.yaml`); gündem özetlerinde yalnız başlık |
| `topics`, `event_type` | deterministik konu etiketleri; `event_type` = öncelik sırasındaki ilk konu (earnings > dividend > …) |

Haber yalnızca bağlamsal kanıttır: sayısal verinin yerine geçmez; içindeki sayılar deterministik araçlarla
doğrulanmadan committed evidence'a giremez. Ticker etiketi olan makale: 847 (30 hisse); "Piyasa özeti" gibi
çok hisse listeleyen özet sayfaları yalnız başlık eşleşmesi tutar. Konu etiketleri anahtar-kelime tabanlıdır (kaba).
