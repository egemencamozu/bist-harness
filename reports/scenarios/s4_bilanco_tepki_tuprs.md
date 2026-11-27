# S4 — Çeyreklik temel değişim ve açıklama sonrası fiyat tepkisi: TUPRS

*FinTreX Analyst senaryo raporu · analiz tarihi 10.09.2026 · dönem 01.01.2024 – 10.09.2026. Bu rapor `eval/scenario_reports.py` ile araç çıktılarından üretilmiştir; metindeki ve tablolardaki her sayı bir araç zarfından gelir (kaynak çağrılar ekte). Eğitsel bir analizdir, yatırım tavsiyesi değildir.*

## Ana bulgular

- TUPRS 2026Ç2 raporu 04.08.2026 18:24 tarihinde açıklandı; yıllık (YTD) hasılat +%42,8, FAVÖK +%122,6.
- 11 açıklamanın ardından 20 günlük ortalama anormal getiri (XU100'e göre) 3,59 puan, medyan -0,75 puan.
- FAVÖK marjı iyileşen ve kötüleşen raporlardan sonraki 20 günlük getiri farkı istatistiksel olarak anlamlı değil (Welch p = 0,685).
- 27 hissenin 16 tanesinde iyileşen raporların ardından ortalama 20 günlük getiri daha yüksek; 1 tanesinde fark p < 0,05. "İyi bilanço = fiyat artışı" genellemesi bu veride desteklenmiyor.

## 1. Soru

> TUPRS için 2024–2026 KAP açıklama tarihleriyle FAVÖK marjı ve Net Borç/FAVÖK nasıl değişti? Açıklamalardan sonraki 1/5/20 günlük XU100 ve sektör sepetine göre anormal getiri nedir? 2026 2. çeyrek bilançosunun 20 günlük penceresi 10.09.2026 itibarıyla tamam mı?

Şartname §14: çeyreklik finansal değişimler, bilgi kamuya açıklandıktan SONRA fiyata nasıl yansıdı; belirli
değişimler tarihsel olarak farklı fiyat tepkileriyle ilişkili mi.

## 2. Yöntem

- **Kaynak:** KAP XBRL mali tabloları; her değer hangi rapordan, hangi saatte açıklandığıyla tutulur. Bir analiz
  tarihinde yalnızca o ana kadar açıklanmış raporlar görünür; revizyonlarda o an bilinen son sürüm seçilir.
- **Tepki baz günü:** işlem günü 18:10 sonrası açıklama → o günün kapanışı; seans öncesi / içi → önceki işlem günü;
  tatil → önceki işlem günü. Ufuklar 1, 5, 20 işlem günü; anormal getiri = hisse − XU100 ve
  hisse − sektör sepeti (PETKM, SASA, AKSA, KORDS).
- **TMS 29:** TUPRS enflasyon muhasebesi uygular. KAP gelir tablosu
  kümülatiftir (YTD); çeyreklik değer YTD farkından çıkarılır ve farklı raporlar farklı satın alma gücündedir → birincil
  karşılaştırma aynı rapordaki yıllık YTD kıyasıdır. 2025 öncesine taşan karşılaştırmalar † ile işaretlidir.
- **Oranlar** (F/K, PD/DD, FD/FAVÖK) hazır kaynaktan alınmaz; analiz tarihindeki fiyat × o ana kadar açıklanmış bilanço ile
  hesaplanır. Şablon: `industrial`; şablona uymayan oranlar hesaplanmaz.
- **Etiket:** iyileşen = FAVÖK marjı önceki rapora göre yükseldi.

## 3. Son rapor: 2026Ç2 (04.08.2026 18:24, [KAP](https://www.kap.org.tr/tr/Bildirim/1643116))

| Kalem | Çeyrek | Yıl başından | Son 12 ay |
| :--- | ---: | ---: | ---: |
| Hasılat | 386,42 milyar TL | 662,79 milyar TL | 1,03 trilyon TL |
| Brüt kâr | 61,04 milyar TL | 84,13 milyar TL | 123,37 milyar TL |
| FAVÖK | 55,45 milyar TL | 71,25 milyar TL | 101,31 milyar TL |
| Esas faaliyet kârı | 46,83 milyar TL | 59,03 milyar TL | 82,51 milyar TL |
| Net kâr (ana ortaklık) | 45,88 milyar TL | 49,85 milyar TL | 67,50 milyar TL |
| Faaliyet nakit akışı | 126,08 milyar TL | 132,37 milyar TL | 166,82 milyar TL |

**Oranlar**

| Oran | Değer | Temel | Not | Neden yok |
| :--- | ---: | :--- | :--- | :--- |
| ROE | %14,80 | ttm | yaklaşık |  |
| ROA | %7,93 | ttm | yaklaşık |  |
| Brüt marj | %12,69 | ytd |  |  |
| FAVÖK marjı | %10,75 | ytd |  |  |
| Esas faaliyet marjı | %8,91 | ytd |  |  |
| Net marj | %7,52 | ytd |  |  |
| Net borç | -127,64 milyar TL | instant |  |  |
| Net borç / FAVÖK | -1,26 | ttm | yaklaşık |  |
| Borç / özkaynak | 0,15 | instant |  |  |
| Cari oran | 1,35 | instant |  |  |
| Likidite oranı | 1,05 | instant |  |  |
| Nakde dönüşüm (FNA / net kâr) | 2,63 | ytd |  |  |

**Değerleme** (10.09.2026 fiyatı 416,75 TL)

| Çarpan | Değer | Neden yok |
| :--- | ---: | :--- |
| F/K | 11,90 |  |
| PD/DD | 1,76 |  |
| FD/FAVÖK | 6,67 |  |

## 4. Rapor rapor fiyat tepkisi

Hasılat ve FAVÖK yıllık (YTD) değişim; FAVÖK marjı değişimi; açıklama sonrası XU100'e göre anormal getiri.

| Dönem | Açıklama | Zamanlama | Hasılat | FAVÖK | FAVÖK marjı Δ | 1g anormal | 5g anormal | 20g anormal | TMS 29 |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| 2023Ç4 | 04.03.2024 19:33 | seans sonrası | -%25,1 | -%6,7 | -0,76 puan | 2,82 puan | 1,14 puan | 7,79 puan | † |
| 2024Ç1 | 22.05.2024 18:29 | seans sonrası | +%3,3 | -%54,2 | -8,30 puan | -0,35 puan | -0,81 puan | -10,75 puan | † |
| 2024Ç2 | 05.08.2024 18:20 | seans sonrası | +%3,6 | -%52,2 | 0,52 puan | 2,92 puan | 5,92 puan | 7,42 puan | † |
| 2024Ç3 | 05.11.2024 18:21 | seans sonrası | -%12,1 | -%60,1 | 0,46 puan | -0,49 puan | -5,00 puan | -8,64 puan | † |
| 2024Ç4 | 17.02.2025 18:26 | seans sonrası | -%18,2 | -%63,5 | -0,44 puan | -3,29 puan | -2,89 puan | -0,91 puan | † |
| 2025Ç1 | 29.04.2025 18:21 | seans sonrası | -%30,6 | -%25,4 | -0,11 puan | 1,27 puan | -4,37 puan | 1,31 puan | † |
| 2025Ç2 | 29.07.2025 18:33 | seans sonrası | -%29,7 | -%22,3 | 0,75 puan | 0,22 puan | -1,55 puan | -4,41 puan |  |
| 2025Ç3 | 31.10.2025 18:19 | seans sonrası | -%25,1 | -%14,3 | 0,76 puan | -0,25 puan | 0,63 puan | -0,75 puan |  |
| 2025Ç4 | 06.02.2026 18:34 | seans sonrası | -%21,7 | -%6,5 | -0,18 puan | -3,77 puan | -5,50 puan | 21,09 puan |  |
| 2026Ç1 | 06.05.2026 18:18 | seans sonrası | +%24,4 | +%23,8 | -1,36 puan | -5,16 puan | -5,33 puan | -7,43 puan |  |
| 2026Ç2 | 04.08.2026 18:24 | seans sonrası | +%42,8 | +%122,6 | 4,63 puan | 4,54 puan | 15,81 puan | 34,81 puan |  |

**Ortalama tepki**

| Ufuk | Rapor | Ort. getiri | Ort. anormal (XU100) | Medyan anormal (XU100) | Ort. anormal (sektör) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| 1g | 11 | +%0,38 | -0,14 puan | -0,25 puan | -0,61 puan |
| 5g | 11 | +%0,43 | -0,18 puan | -1,55 puan | -1,14 puan |
| 20g | 11 | +%6,02 | 3,59 puan | -0,75 puan | 4,36 puan |

**İyileşen ve kötüleşen raporlar (20 günlük getiri)**

| Grup | n | Ortalama | Medyan | Pozitif oran | En düşük / en yüksek |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Kötüleşen | 6 | +%1,85 | +%0,20 | %50 | -%10,7 / +%21,1 |
| İyileşen | 5 | +%5,69 | -%0,75 | %40 | -%8,6 / +%34,8 |

Welch t testi p = 0,685.

## 5. Bütün hisseler

Aynı ayrım ders evrenindeki her hisse için (20 günlük getiri, iyileşen / kötüleşen rapor sayısı):

| Hisse | Şablon | İyileşen / kötüleşen | İyileşen ort. | Kötüleşen ort. | p |
| :--- | :--- | ---: | ---: | ---: | ---: |
| ASELS | industrial | 6 / 5 | +%11,14 | +%1,69 | 0,278 |
| TUPRS | industrial | 5 / 6 | +%5,69 | +%1,85 | 0,685 |
| BIMAS | industrial | 6 / 4 | +%0,68 | +%5,57 | 0,310 |
| THYAO | industrial | 4 / 7 | +%2,00 | -%4,20 | 0,280 |
| AKBNK | bank | 8 / 3 | -%1,57 | +%7,54 | 0,115 |
| KCHOL | holding | 5 / 6 | -%1,14 | +%2,21 | 0,477 |
| EREGL | industrial | 6 / 5 | -%2,83 | +%5,44 | 0,238 |
| TCELL | industrial | 6 / 5 | +%2,13 | -%4,91 | 0,101 |
| CCOLA | industrial | 5 / 6 | -%4,26 | +%4,30 | 0,024 |
| MGROS | industrial | 6 / 5 | -%0,33 | -%5,15 | 0,609 |
| SASA | industrial | 4 / 7 | -%10,01 | -%1,33 | 0,051 |
| FROTO | industrial | 1 / 10 | +%11,84 | -%2,64 | – |
| ENKAI | industrial | 6 / 4 | +%0,01 | +%0,31 | 0,967 |
| PGSUS | industrial | 5 / 6 | -%6,98 | +%0,66 | 0,117 |
| MPARK | industrial | 5 / 6 | +%5,45 | +%0,66 | 0,489 |
| EKGYO | reit | 5 / 5 | +%11,27 | -%4,23 | 0,102 |
| GUBRF | industrial | 6 / 4 | -%2,54 | +%6,50 | 0,180 |
| ENJSA | industrial | 5 / 6 | -%0,89 | -%0,91 | 0,997 |
| TTKOM | industrial | 8 / 3 | +%0,21 | -%0,20 | 0,961 |
| OYAKC | industrial | 4 / 7 | +%7,52 | -%0,51 | 0,246 |
| AKSEN | industrial | 7 / 4 | +%2,52 | -%2,41 | 0,601 |
| ARCLK | industrial | 4 / 7 | -%2,72 | -%4,69 | 0,708 |
| ECILC | industrial | 4 / 7 | -%0,99 | +%3,22 | 0,311 |
| MAVI | industrial | 4 / 6 | +%9,46 | -%1,37 | 0,326 |
| PETKM | industrial | 6 / 5 | -%2,38 | -%4,29 | 0,736 |
| TOASO | industrial | 2 / 9 | +%3,95 | -%1,74 | 0,410 |
| KRDMD | industrial | 7 / 3 | -%1,79 | -%0,41 | 0,796 |

27 hissenin 16 tanesinde iyileşen raporlardan sonra ortalama getiri daha yüksek, 1 tanesinde fark
p < 0,05. Hisse başına rapor sayısı küçük (yaklaşık 10–11); tek tek sonuçlar zayıf kanıttır.

## 6. Sektöre özgü oranlar: banka örneği (AKBNK)

Şartname "banka analizi sanayi şirketi oranlarını körü körüne kullanmamalı" diyor. Banka şablonunda FAVÖK'e dayalı
oranlar ve cari oran hesaplanmaz:

| Oran | Değer | Not |
| :--- | ---: | :--- |
| ROE | %20,55 |  |
| ROA | %1,66 |  |
| loans_to_deposits | 0,89 |  |
| equity_to_assets | %8,09 |  |
| cost_to_income | %50,06 |  |
| Cari oran | – | şablona uygun değil |
| FAVÖK marjı | – | şablona uygun değil |
| Net borç / FAVÖK | – | şablona uygun değil |
| Likidite oranı | – | şablona uygun değil |

## 7. Backtest

`C_TECH_SECTOR_FUND` varyantı (Teknik + sektör + temel), önceden sabitlenmiş kural:

| Ölçüt | Değer |
| :--- | ---: |
| Dönem | 02.01.2024 – 10.09.2026 |
| Sinyal / kapanan işlem | 2 / 2 |
| Kazanan oranı | %100,0 |
| Kümülatif getiri (nominal) | +%0,83 |
| Reel getiri (TÜFE) | -%56,28 |
| XU100'e göre fark | -83,46 puan |
| Eşit ağırlıklı al-tut'a göre fark | -278,02 puan |
| Sharpe (rf = 0 / politika faizi) | 0,09 / -8,13 |
| En büyük düşüş | -%4,94 |
| Örneklem içi (02.01.2024 – 31.12.2025) | +%0,65, Sharpe 0,22 |
| Örneklem dışı (02.01.2026 – 10.09.2026) | +%0,18, Sharpe 0,07 |

## 8. Harness kararı

Aynı soru 17 adımlı harness'tan geçirildi (senaryo planlayıcı + kural tabanlı açıklayıcı): **WATCH**, risk kapısı **INVESTIGATE** (24 bulgu; türler: INSUFFICIENT_SAMPLE, MISSING_DAY, SPARSE_NEWS, SPEECH_NOT_AVAILABLE, TMS29_DECUMULATION_APPROX, TMS29_WARNING). 15 araç çağrısı, 0 geçersiz.

Sistemin açıklaması (kanıt numaraları E# ile):

> TUPRS için 2026Ç2 dönemi finansal raporu KAP'ta 04.08.2026 18:24 tarihinde yayımlandı; analiz yalnız bu tarihe kadar açıklanmış verileri kullanır (E1). TUPRS 2026Ç2 raporunda FAVÖK marjı önceki rapordaki %6,12 değerinden %10,75 değerine yükseldi (4,63 puan) (E5). TUPRS için 11 rapor açıklamasının ardından 20 günlük XU100'e göre ortalama anormal getiri 3,59 puan (medyan -0,75 puan) (E10). Varyant C_TECH_SECTOR_FUND (01.01.2024–10.09.2026, işlem başı 10 baz puan maliyet): 2 kapanmış işlem, kazanan oranı %100,00; kümülatif getiri +%0,83, XU100'ün altında (TÜFE'ye göre reel -%56,28); XU100 +%84,29, eşit ağırlıklı al-tut +%278,85; Sharpe 0,09 (politika faizine göre -8,13); en büyük düşüş -%4,94 (E12). Son raporda iyileşme var (E5), ancak geçmiş fiyat tepkisi ya da strateji testi bunu desteklemiyor (E10, E12). Risk kapısı sonucu INVESTIGATE (E13).
>
> Sonuçlar geçmiş veriye dayanır; korelasyon nedensellik değildir.
>
> Bu çıktı eğitsel bir analizdir; geçmiş sonuçlar gelecekteki getirinin göstergesi değildir ve yatırım tavsiyesi değildir.

## 9. Sınırlar

- Hisse başına çeyrek sayısı az (2023Ç4 – 2026Ç2); TMS 29 geçişi eski çeyreklerle kıyası zorlaştırır.
- Sürpriz, piyasa beklentisine göre değil önceki rapora göre tanımlanır (analist konsensüs verisi yok).
- Açıklama penceresine denk gelen başka haberler ayrıştırılmaz.

## Ek — kaynak araç çağrıları

Analiz `A-20261127013524399121-7905192c` · karar `D-20261127013524399121-7905192c` · episodik kayıt `reports/scenarios/episodic_q4.sqlite`.

Veri sürümü (sha256, ilk 12): fundamentals `41b26fc0d037`, macro `7c8f1f74f52e`, news `cfba92ab38d9`, prices `330c06c5e4c9`

| Adım | Araç | Kaynak | call_id |
| :--- | :--- | :--- | :--- |
| LOAD_MARKET_DATA | `get_stock_history` | plan | `94d46d260086b0f3` |
| LOAD_MARKET_DATA | `get_index_history` | plan | `d27ba4b9d88d0542` |
| CHECK_DATA_QUALITY | `check_data_quality` | harness | `ba894efb4de9673d` |
| CALCULATE_TECHNICALS | `calculate_indicators` | plan | `0573da77e0916a63` |
| LOAD_FUNDAMENTALS | `get_fundamental_metrics` | plan | `44a2ac73a6866782` |
| LOAD_FUNDAMENTALS | `calculate_fundamental_change` | plan | `bdb6eaa458ad548a` |
| LOAD_MACRO_CONTEXT | `get_macro_context` | plan | `49fa028967f92c06` |
| LOAD_NEWS_AND_SPEECH_CONTEXT | `get_news_events` | plan | `2e038669d383f882` |
| LOAD_NEWS_AND_SPEECH_CONTEXT | `get_speech_features` | plan | `1431a40eda670442` |
| BUILD_EVIDENCE | `build_evidence_bundle` | harness | `ce97be256b823332` |
| PREVIEW_STRATEGIES | `run_backtest` | plan | `9b06cb888f629c53` |
| RUN_BACKTEST | `run_backtest` | plan | `f69d9cb0c0a99778` |
| RUN_BACKTEST | `build_evidence_bundle` | harness | `35453de97f0816da` |
| RISK_GATE | `check_data_quality` | harness | `2f7e23215ff1a257` |
| RISK_GATE | `build_evidence_bundle` | harness | `e68d69b3f6244fe2` |

**Karşılaştırma için ek araç çağrıları** (harness dışı, aynı snapshot ve as_of)

| Kapsam | Araç | call_id |
| :--- | :--- | :--- |
| ASELS | `calculate_fundamental_change` | `c52ad2373ee7c408` |
| TUPRS | `calculate_fundamental_change` | `bdb6eaa458ad548a` |
| BIMAS | `calculate_fundamental_change` | `c95efabf74299449` |
| THYAO | `calculate_fundamental_change` | `676cdf116f820e8c` |
| AKBNK | `calculate_fundamental_change` | `bcabbb8bd69ead7d` |
| KCHOL | `calculate_fundamental_change` | `361a542b27199273` |
| EREGL | `calculate_fundamental_change` | `855c7060d2ba64de` |
| TCELL | `calculate_fundamental_change` | `2a57d53218159cd0` |
| CCOLA | `calculate_fundamental_change` | `88103164625a624e` |
| MGROS | `calculate_fundamental_change` | `10ebbd7b0b303128` |
| SASA | `calculate_fundamental_change` | `56ac218b4517ad74` |
| TRALT | `calculate_fundamental_change` | `76c416df9e663130` |
| FROTO | `calculate_fundamental_change` | `0e35b5d5ef8d7da2` |
| ENKAI | `calculate_fundamental_change` | `4d170cdc1b53893a` |
| PGSUS | `calculate_fundamental_change` | `f65f42a086c1906e` |
| MPARK | `calculate_fundamental_change` | `9056d058ae86fa1f` |
| EKGYO | `calculate_fundamental_change` | `d2477753d93028ba` |
| GUBRF | `calculate_fundamental_change` | `f051c1650301bbf4` |
| TURSG | `calculate_fundamental_change` | `41b933b4ee43ceee` |
| ENJSA | `calculate_fundamental_change` | `b9264dbf6b3c29b1` |
| TTKOM | `calculate_fundamental_change` | `ec7ab3dfca02ae76` |
| OYAKC | `calculate_fundamental_change` | `dfbd92ed803cac2c` |
| AKSEN | `calculate_fundamental_change` | `5e02e365657a055c` |
| ISMEN | `calculate_fundamental_change` | `40caad1ab2ab6001` |
| ARCLK | `calculate_fundamental_change` | `6a49b9d918fe8214` |
| ECILC | `calculate_fundamental_change` | `18d89773f63dad9d` |
| MAVI | `calculate_fundamental_change` | `f4b1c1260b41edc9` |
| PETKM | `calculate_fundamental_change` | `7d6f8256bb6825da` |
| TOASO | `calculate_fundamental_change` | `906fa3ce67457ee3` |
| KRDMD | `calculate_fundamental_change` | `618c0a9b7f00ece0` |
| AKBNK şablon farkı | `get_fundamental_metrics` | `c02324cc2260f565` |
