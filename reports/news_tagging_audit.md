# News tagging precision audit (2026-11-23)

Source: Bloomberg HT archive, frozen snapshot `data/raw/news_bloomberght/2026-11-20` (40,780 articles). Tagger:
`src/bistharness/data/ingest/news.py` + `config/news.yaml` (deterministic rules, no LLM). Unit: an (article, stock)
pair. Grading: by Claude, reading the headline and the matched text passage; the user can re-check every row (each row
links to its URL). Headlines are quoted in the original Turkish because they are source citations.

**Classes.** *correct* = the company is the subject of the article or the article carries concrete company-specific
information (contract, rating, stake, results, trading measure); *weak* = the company really appears but in a side role
(IPO intermediary, award, subsidiary, an executive's comment); *wrong* = not that company (another entity with the same
word, a market term, an event or venue name, a scraping error) or only a person's title.

**Method (two rounds to avoid bias).** Round 1 = the first rule set + 66 new stocks, 100 random pairs (seed 2026); the
systematic errors found were fixed (exclusion lists + a rule for another article's headline copied into the text).
Round 2 = the corrected rules, 100 new random pairs NOT overlapping round 1 (seed 4242), drawn before seeing any result
= an unbiased measurement. NO rule was added for errors seen in round 2 (otherwise the measurement would be biased
again); they are listed as known limitations.

## Round 1 (before the fixes; the fixes were designed from this sample)

- correct 92, weak 3, wrong 5 (n = 100)
- strict precision (correct only): 92% (95% CI 85.0%–95.9%)
- broad precision (correct + weak = the company really appears): 95% (95% CI 88.8%–97.8%)
- headline matches: 71/72 correct; body/code matches: 21/28 correct, 3 weak, 4 wrong

## Round 2 (after the fixes, unbiased)

- correct 90, weak 7, wrong 3 (n = 100)
- strict precision (correct only): 90% (95% CI 82.6%–94.5%)
- broad precision (correct + weak = the company really appears): 97% (95% CI 91.5%–99.0%)
- headline matches: 67/67 correct; body/code matches: 23/33 correct, 7 weak, 3 wrong

## Conclusion and limitations

- Headline matches: 71/72 in round 1 (the single error, a "Yapı Kredi Yatırım: ..." market note, became a rule) and
  67/67 in round 2. The remaining errors are in body matches (round 2: 3 wrong and 7 weak out of 33).
- Round 1's systematic errors became rules: 'Türkiye Sigorta Birliği' and 'Türkiye sigorta piyasası/sektörü' (the
  insurance association / market, not TURSG), 'Enerjisa Üretim' (not listed), research notes of 'Yapı Kredi
  Yatırım/Portföy' and 'Garanti BBVA Yatırım/Portföy', the event name 'Albaraka Zirveleri'; if another article's
  headline appears verbatim in the text (a sidebar or a "last week" summary) that part is not counted (about 32 articles
  in the archive carried the same Vestel headline).
- Error types left in round 2 (not turned into rules): a person's title ('Koç Holding board member'), a biography, a
  venue name ('VakıfBank Sanat Galerisi').
- Impact: in this project news is contextual evidence only (the number of tagged articles in the last 30 days); the
  decision policy does not use news and numbers inside news never become evidence. A wrong tag changes no number and no
  action.
- Not measured: recall (missed articles). Single body mentions (`min_body_mentions: 2`) are deliberately not counted;
  short names ("Koç'tan") may not be recognised in headlines.
- Coverage: 83 of the 96 stocks have at least one article; none for ALGYO, ARDYZ, AYEN, BERA, CEMTS, DEVA, ECZYT,
  EGEEN, GOODY, KATMR, LOGO, NUHCM, ODAS.
- Source choice: Bloomberg HT only. The general newspapers (Sabah, Cumhuriyet, Habertürk, Sözcü, Takvim) and Telegram
  channels (BPT Finans, Para Ajansı, ...) in the FinTreX archive were not used in the course project (general news -> more
  false matches; the same story on 5-6 sites -> deduplication needed; no full text on Telegram). They are left for the
  TÜBİTAK/FinTreX phase.

## Round 1 sample

| # | Stock | Match | Class | Headline (original Turkish) | Note |
|---|---|---|---|---|---|
| 1 | ASELS | title | correct | [Aselsan'dan NATO ile stratejik işbirliği](https://www.bloomberght.com/aselsan-dan-nato-ile-stratejik-isbirligi-3782104) |  |
| 2 | EKGYO | body | correct | [Gayrimenkul sertifikasına yaklaşık iki katlık talep](https://www.bloomberght.com/gayrimenkul-sertifikasina-yaklasik-iki-katlik-talep-3754553) |  |
| 3 | MGROS | title | correct | [Migros ilk çeyrekte 51 mağaza açtı; mağaza sayısı 3 bin 812'ye ulaştı](https://www.bloomberght.com/migros-ilk-ceyrekte-51-magaza-acti-magaza-sayisi-3-bin-812-ye-ulasti-3776751) |  |
| 4 | AKBNK | body | correct | [Morgan Stanley Türk bankalarını mercek altına aldı](https://www.bloomberght.com/morgan-stanley-turk-bankalarini-mercek-altina-aldi-3786582) |  |
| 5 | SISE | title | correct | [Şişecam UK, dolar tahvil yatırımcı görüşmeleri için yetki verdi / Son dakika ekonomi haberleri](https://www.bloomberght.com/sisecam-uk-dolar-tahvil-yatirimci-gorusmeleri-icin-yetki-verdi-3766016) |  |
| 6 | YKBNK | title | correct | [Yapı Kredi'de sermaye benzeri borçlanma hazırlığı](https://www.bloomberght.com/yapi-kredi-de-sermaye-benzeri-borclanma-hazirligi-3763041) |  |
| 7 | ASELS | title | correct | [Aselsan'dan 109,7 milyon dolarlık sözleşme](https://www.bloomberght.com/aselsan-dan-109-7-milyon-dolarlik-sozlesme-2355802) |  |
| 8 | ISCTR | title | correct | [İş Bankası ve TSKB'den güneşe 100 milyon euroluk finansman](https://www.bloomberght.com/yerli-teknolojiye-100-milyon-euroluk-ortak-finansman-3768838) |  |
| 9 | TSKB | code | weak | [Dünya Bankası'ndan Türkiye'ye ek 18 milyar dolarlık finansman](https://www.bloomberght.com/dunya-bankasi-ndan-turkiye-ye-ek-18-milyar-dolarlik-finansman-2354262) | World Bank speech at an event organised by TSKB |
| 10 | VESTL | body | correct | [Zorlu Grubu'ndan finansal yeniden yapılandırma başvurusu](https://www.bloomberght.com/zorlu-grubu-ndan-finansal-yeniden-yapilandirma-basvurusu-3781350) |  |
| 11 | SAHOL | title | correct | ["Sabancı'nın dünyanın 18 farklı ülkesinde ayak izi bulunuyor"](https://www.bloomberght.com/sabanci-holding-in-turkiye-onceligi-devam-edecek-3767471) |  |
| 12 | SISE | title | correct | [Şişecam 2025 yılını 9,9 milyar TL net kâr ile tamamladı](https://www.bloomberght.com/sisecam-2025-yilini-9-9-milyar-tl-net-kr-ile-tamamladi-3769331) |  |
| 13 | PGSUS | title | correct | [Pegasus ve THY uçakları geri dönüyor](https://www.bloomberght.com/pegasus-ve-thy-ucaklari-geri-donuyor-2350951) |  |
| 14 | ISCTR | title | correct | [İş Bankası/Aran: 2026 Mayıs ayında normalleşme olur](https://www.bloomberght.com/is-bankasiaran-2026-mayis-ayinda-normallesme-olur-3754664) |  |
| 15 | TCELL | title | correct | [Turkcell Genel Müdürlüğü'ne Ali Taha Koç atandı](https://www.bloomberght.com/turkcell-genel-mudurlugu-ne-ali-taha-koc-atandi-2340083) |  |
| 16 | ASELS | title | correct | [Roketsan'dan Aselsan'a yeni sipariş](https://www.bloomberght.com/roketsan-dan-aselsan-a-yeni-siparis-2354813) |  |
| 17 | THYAO | title | correct | [THY ve Pegasus İsrail uçuşlarına ara verdi](https://www.bloomberght.com/pegasus-israil-ucuslarina-ara-verdi-2339892) |  |
| 18 | VESTL | title | correct | [Vestel, Çinli yayın platformunda hisse alıyor](https://www.bloomberght.com/vestel-cinli-yayin-platformunda-hisse-aliyor-2360514) |  |
| 19 | TSKB | title | correct | [TSKB, Aksa Yenilenebilir Enerji ile yeni bir kredi anlaşmasına imza attı](https://www.bloomberght.com/tskb-aksa-yenilenebilir-enerji-ile-yeni-bir-kredi-anlasmasina-imza-atti-3753561) |  |
| 20 | TTRAK | title | correct | [Türk Traktör'den yeni yatırım kararı](https://www.bloomberght.com/turk-traktor-den-yeni-yatirim-karari-3736282) |  |
| 21 | TTKOM | title | correct | [Türk Telekom'dan beklenti üstü net kâr](https://www.bloomberght.com/turk-telekom-dan-beklenti-ustu-net-kr-3776875) |  |
| 22 | KORDS | title | correct | [Kordsa'nın yeni CEO'su belli oldu](https://www.bloomberght.com/kordsa-nin-yeni-ceo-su-belli-oldu-3749134) |  |
| 23 | TUPRS | title | correct | [Tüpraş İstanbul Havalimanı’na 1,8 milyon ton jet yakıtı satacak](https://www.bloomberght.com/tupras-istanbul-havalimanina-1-8-milyon-ton-jet-yakiti-satacak-2363221) |  |
| 24 | TTKOM | title | correct | [Türk Telekom’dan enerjiden yapay zekaya büyüme hamlesi](https://www.bloomberght.com/turk-telekomdan-enerjiden-yapay-zekaya-buyume-hamlesi-3789696) |  |
| 25 | SAHOL | title | correct | [Sabancı'dan ABD'de güneş enerjisi yatırımı](https://www.bloomberght.com/sabanci-dan-abd-de-gunes-enerjisi-yatirimi-3752301) |  |
| 26 | GARAN | body | correct | [JPMorgan dört Türk bankasını negatif izlemeye aldı](https://www.bloomberght.com/jpmorgan-dort-turk-bankasini-negatif-izlemeye-aldi-2346084) |  |
| 27 | ENJSA | title | correct | [Enerjisa'dan ikinci çeyrekte 512,3 milyon TL net kâr](https://www.bloomberght.com/enerjisa-dan-ikinci-ceyrekte-512-3-milyon-tl-net-kr-3754602) |  |
| 28 | EKGYO | body | weak | [15 soruda "Yarısı Bizden" kampanyası](https://www.bloomberght.com/15-soruda-yarisi-bizden-kampanyasi-3734286) | the campaign homes are built by TOKİ or Emlak Konut |
| 29 | SASA | title | correct | [SASA'dan hisse geri alım kararı](https://www.bloomberght.com/sasa-dan-hisse-geri-alim-karari-2359100) |  |
| 30 | ARCLK | title | correct | [Arçelik'ten Bangladeş'te üretim açıklaması](https://www.bloomberght.com/arcelik-ten-banglades-te-uretim-aciklamasi-2361819) |  |
| 31 | ASELS | title | correct | [Aselsan'dan 35 milyon dolarlık sözleşme](https://www.bloomberght.com/aselsan-dan-35-milyon-dolarlik-sozlesme-2350134) |  |
| 32 | ISCTR | body | correct | [Galataport bankalarla yapılandırma anlaşması imzaladı](https://www.bloomberght.com/galataport-bankalarla-yapilandirma-anlasmasi-imzaladi-3737169) |  |
| 33 | ULKER | title | correct | [Ülker Bisküvi 5 yıl vadeli 250 milyon dolar sendikasyon kredisi sağladı](https://www.bloomberght.com/ulker-biskuvi-5-yil-vadeli-250-milyon-dolar-sendikasyon-kredisi-sagladi-3758608) |  |
| 34 | ASELS | title | correct | [Aselsan, BMC ile yeni sözleşme imzaladı](https://www.bloomberght.com/aselsan-bmc-ile-yeni-sozlesme-imzaladi-3742401) |  |
| 35 | KRDMD | title | correct | [Kardemir/Demir: Rüzgar ve jeotermalde büyük yatırımlara başlayacağız](https://www.bloomberght.com/kardemirdemir-ruzgar-ve-jeotermalde-buyuk-yatirimlara-baslayacagiz-2348698) |  |
| 36 | HALKB | body | correct | [7 başlıkla geçen hafta](https://www.bloomberght.com/7-baslikla-gecen-hafta-3780726) |  |
| 37 | ULKER | title | correct | [Ülker, 2024 yılı ilk çeyrek finansallarını açıkladı](https://www.bloomberght.com/ulker-2024-yili-ilk-ceyrek-finansallarini-acikladi-2353853) |  |
| 38 | ZOREN | title | correct | [Zorlu Enerji 2030 vadeli dolar tahvili rekor düşüşe ilerliyor](https://www.bloomberght.com/zorlu-enerji-2030-vadeli-dolar-tahvili-rekor-dususe-ilerliyor-3788254) |  |
| 39 | ALBRK | body | wrong | [TCMB Başkanı Karahan, "İstanbul Dünya İslam Ekonomisi Zirvesi"nde konuştu](https://www.bloomberght.com/tcmb-baskani-karahan-istanbul-dunya-islam-ekonomisi-zirvesinde-konustu-3749598) | event name: 'Türkiye Albaraka Zirveleri' |
| 40 | KORDS | title | correct | [Kordsa'dan sermaye artırımı kararı](https://www.bloomberght.com/kordsa-dan-sermaye-artirimi-karari-3788684) |  |
| 41 | TAVHL | title | correct | [Tav Havalimanları'ndan ikinci çeyrekte beklenti üstü net kâr](https://www.bloomberght.com/tav-havalimanlari-ndan-ikinci-ceyrekte-beklenti-ustu-net-kr-3784031) |  |
| 42 | GARAN | title | correct | [Garanti BBVA/Akten: Enflasyondaki düşüş bizi pozitif etkiledi](https://www.bloomberght.com/garanti-bbvaakten-enflasyondaki-dusus-bizi-pozitif-etkiledi-3741887) |  |
| 43 | TSKB | code | weak | [Dof Robotik halka arz sonuçları açıklandı](https://www.bloomberght.com/dof-robotik-halka-arz-sonuclari-aciklandi-3756669) | lead of the IPO consortium |
| 44 | ISCTR | title | correct | [İş Bankası Genel Müdürü Hakan Aran görevden ayrılıyor](https://www.bloomberght.com/is-bankasi-genel-muduru-hakan-aran-gorevden-ayriliyor-3784994) |  |
| 45 | TKFEN | body | wrong | [Ercan Kumcu yaşamını yitirdi](https://www.bloomberght.com/ercan-kumcu-yasamini-yitirdi-3754521) | obituary; the person's former title |
| 46 | HALKB | title | correct | [Halkbank'tan ABD'deki dava sürecine ilişkin açıklama](https://www.bloomberght.com/halkbank-tan-abd-deki-dava-surecine-iliskin-aciklama-3771384) |  |
| 47 | HALKB | title | correct | [Halkbank’ta esnafa faiz artışı geçmişe uygulanmayacak](https://www.bloomberght.com/halkbankta-esnafa-faiz-artisi-gecmise-uygulanmayacak-2353386) |  |
| 48 | TURSG | title | correct | [Türkiye Sigorta ve PTT AŞ güçlerini birleştirdi! / Son dakika ekonomi haberleri](https://www.bloomberght.com/turkiye-sigorta-ve-ptt-as-guclerini-birlestirdi-3742110) |  |
| 49 | ISCTR | body | correct | [HSBC: Türk bankalarının değerlemelerinde yükseliş potansiyeli var](https://www.bloomberght.com/hsbc-turk-bankalarinin-degerlemelerinde-yukselis-potansiyeli-var-3790367) |  |
| 50 | VESTL | body | wrong | [TÜFE ana harcama gruplarına göre yıllık değişim oranları](https://www.bloomberght.com/tufe-ana-harcama-gruplarina-gore-yillik-degisim-oranlari-3787265) | scraping error: another article's headline in a sidebar |
| 51 | ISCTR | body | correct | [Morgan Stanley, Türk bankalarında hedef düşürdü](https://www.bloomberght.com/morgan-turk-bankalarinda-hedef-dusurdu-2357038) |  |
| 52 | SISE | title | correct | [Şişecam'dan yurt dışında şirket](https://www.bloomberght.com/sisecam-dan-yurt-disinda-sirket-2341425) |  |
| 53 | ARCLK | title | correct | [Arçelik'in kurumsal markası Beko oluyor](https://www.bloomberght.com/arcelik-in-kurumsal-markasi-beko-oluyor-2350608) |  |
| 54 | TOASO | title | correct | [Tofaş'tan Rekabet'in Stellantis kararına yönelik açıklama: Süreç devam ediyor](https://www.bloomberght.com/tofas-tan-rekabet-in-stellantis-kararina-yonelik-aciklama-surec-devam-ediyor-2363113) |  |
| 55 | HALKB | title | correct | [Halkbank davası düşürüldü](https://www.bloomberght.com/halkbank-davasi-dusuruldu-3780340) |  |
| 56 | ASELS | title | correct | [Aselsan Genel Müdürü Akyol: Bakiye siparişler 20 milyar doları aştı](https://www.bloomberght.com/aselsan-3770194) |  |
| 57 | PGSUS | title | correct | [Pegasus yeni uçak siparişlerini değerlendiriyor](https://www.bloomberght.com/pegasus-yeni-ucak-siparislerini-degerlendiriyor-2343634) |  |
| 58 | OYAKC | title | correct | [OYAK Çimento'dan 3. çeyrekte 3,4 milyar lira net kâr](https://www.bloomberght.com/oyak-cimento-dan-3-ceyrekte-3-4-milyar-lira-net-kr-3760699) |  |
| 59 | GARAN | title | correct | [Garanti BBVA çift dilimli sendikasyon sağladı](https://www.bloomberght.com/garanti-bbva-cift-dilimli-sendikasyon-sagladi-2354457) |  |
| 60 | TSKB | code | correct | [Galataport bankalarla yapılandırma anlaşması imzaladı](https://www.bloomberght.com/galataport-bankalarla-yapilandirma-anlasmasi-imzaladi-3737169) |  |
| 61 | KCHOL | title | correct | [Koç Holding, 19,7 milyar TL ile beklentilerin üzerinde net kâr elde etti](https://www.bloomberght.com/koc-holding-19-7-milyar-tl-ile-beklentilerin-uzerinde-net-kr-elde-etti-3784802) |  |
| 62 | ASELS | title | correct | [ASELSAN’dan 271,5 milyon dolarlık yeni savunma sözleşmesi](https://www.bloomberght.com/aselsandan-271-5-milyon-dolarlik-yeni-savunma-sozlesmesi-3779011) |  |
| 63 | YKBNK | title | wrong | [Yapı Kredi Yatırım: Sis kalkıyor ama yol hâlâ dar](https://www.bloomberght.com/yapi-kredi-yatirim-sis-kalkiyor-ama-yol-hl-dar-3767688) | Yapı Kredi Yatırım's market outlook note, not about the bank |
| 64 | SISE | title | correct | [Şişecam İtalya’daki yeni hat yatırımını tamamladı](https://www.bloomberght.com/sisecam-italyadaki-yeni-hat-yatirimini-tamamladi-3769573) |  |
| 65 | THYAO | title | correct | [THY Elektronik Para ve Ödeme Hizmetleri A.Ş.'ye faaliyet izni](https://www.bloomberght.com/thy-elektronik-para-ve-odeme-hizmetleri-as-ye-faaliyet-izni-3745071) |  |
| 66 | TOASO | title | correct | [Tofaş beklenti üzeri kâr açıkladı](https://www.bloomberght.com/tofas-beklenti-uzeri-kr-acikladi-3768739) |  |
| 67 | SAHOL | title | correct | [Sabancı, ABD'li şirkete yatırım yaptı](https://www.bloomberght.com/sabanci-abd-li-sirkete-yatirim-yapti-2343555) |  |
| 68 | GARAN | title | correct | [Garanti BBVA sendikasyon sağladı](https://www.bloomberght.com/garanti-bbva-sendikasyon-sagladi-3736069) |  |
| 69 | AKBNK | title | correct | [Akbank Genel Müdürü Gür'den 2026 öngörüleri / Son dakika ekonomi haberleri](https://www.bloomberght.com/akbank-genel-muduru-gur-den-2026-ongoruleri-3762035) |  |
| 70 | TURSG | body | wrong | [“Yabancı risk almakta iştahlı davranmıyor”](https://www.bloomberght.com/yabanci-risk-almakta-istahli-davranmiyor-2345598) | 'Türkiye sigorta piyasası' = the insurance sector, not the company |
| 71 | THYAO | title | correct | [THY'den ek sefer ve tavan fiyat açıklaması / Son dakika ekonomi haberleri](https://www.bloomberght.com/thy-yurt-ici-bilet-tavan-fiyatini-1750-lira-olarak-belirledi-3746992) |  |
| 72 | AKBNK | body | correct | [HSBC'den Türk bankacılık sektörü analizi](https://www.bloomberght.com/hsbc-den-turk-banka-hissesi-yorumu-2353789) |  |
| 73 | THYAO | body | correct | [Havayolu ulaşımına kar engeli / Son dakika ekonomi haberleri](https://www.bloomberght.com/havayolu-ulasimina-kar-engeli-3765963) |  |
| 74 | FROTO | body | correct | [Koç Holding CEO'su Çakıroğlu'ndan Davos'ta dijital dönüşüm mesajı](https://www.bloomberght.com/koc-holding-ceosu-cakiroglundan-davos-ta-dijital-donusum-mesaji-3767173) |  |
| 75 | ISCTR | title | correct | [İş Bankası/Aran: Kredilerde enflasyon beklentileriyle uyumlu gidişat var](https://www.bloomberght.com/is-bankasiaran-kredilerde-enflasyon-beklentileriyle-uyumlu-gidisat-var-3755612) |  |
| 76 | ASELS | title | correct | [Aselsan 44,4 milyon dolarlık ihracat sözleşmeleri imzaladı](https://www.bloomberght.com/aselsan-44-4-milyon-dolarlik-ihracat-sozlesmeleri-imzaladi-2360726) |  |
| 77 | ISCTR | title | correct | [İş Bankası’ndan beklentilerin üzerinde kâr performansı](https://www.bloomberght.com/is-bankasi-ikinci-ceyrekte-17-4-milyar-tl-net-kr-acikladi-3754249) |  |
| 78 | KORDS | body | correct | [Sabancı'dan 3. çeyrekte 679 milyon lira konsolide net kâr](https://www.bloomberght.com/sabanci-dan-3-ceyrekte-679-milyon-lira-konsolide-net-kr-3760800) |  |
| 79 | PGSUS | title | correct | [Pegasus'un eurobondunda teklif süreci başladı](https://www.bloomberght.com/pegasus-un-eurobondunda-teklif-sureci-basladi-2359391) |  |
| 80 | TSKB | code | correct | [Lopez: Orta Koridor’un ilk kısmının faaliyete geçmesi gerekiyor](https://www.bloomberght.com/lopez-orta-koridorun-ilk-kisminin-faaliyete-gecmesi-gerekiyor-2342566) |  |
| 81 | YKBNK | title | correct | [Yapı Kredi dolar cinsi tahvil ihraç ediyor / Son dakika ekonomi haberleri](https://www.bloomberght.com/yapi-kredi-dolar-cinsi-tahvil-ihrac-ediyor-3742361) |  |
| 82 | ASELS | title | correct | [Aselsan'dan beklenti üstü kâr](https://www.bloomberght.com/aselsan-dan-beklenti-ustu-kr-3760810) |  |
| 83 | ISCTR | title | correct | [İş Bankası’ndan 500 milyon dolarlık Eurotahvil ihracı](https://www.bloomberght.com/is-bankasindan-500-milyon-dolarlik-eurotahvil-ihraci-3767869) |  |
| 84 | MGROS | title | correct | [Migros/Tort: Ürünlerimizde trend olarak düşen enflasyonu görüyoruz](https://www.bloomberght.com/migros-tort-urunlerimizde-trend-olarak-dusen-enflasyonu-goruyoruz-2361381) |  |
| 85 | TURSG | title | correct | [Türkiye Sigorta'dan ikinci çeyrekte 7 milyar TL net kâr](https://www.bloomberght.com/turkiye-sigorta-dan-ikinci-ceyrekte-7-milyar-tl-net-kr-3783279) |  |
| 86 | TUPRS | title | correct | [Tüpraş'ın temettü tarihi netleşti](https://www.bloomberght.com/tupras-in-temettu-tarihi-netlesti-2350414) |  |
| 87 | YKBNK | title | correct | [Yapı Kredi, deprem bölgesine 80 milyon dolarlık kaynak sağladı](https://www.bloomberght.com/yapi-kredi-deprem-bolgesine-80-milyon-dolarlik-kaynak-sagladi-2344098) |  |
| 88 | SAHOL | title | correct | [Sabancı Holding, “Dünyanın En İyi 25 İşvereni” arasında](https://www.bloomberght.com/sabanci-holding-dunyanin-en-iyi-25-isvereni-arasinda-3789869) |  |
| 89 | YKBNK | title | correct | [Yapı Kredi ve TEB'de yurt dışı borçlanma hazırlığı](https://www.bloomberght.com/yapi-kredi-ve-teb-de-yurt-disi-borclanma-hazirligi-2359474) |  |
| 90 | ISCTR | title | correct | [İş Bankası ikinci çeyrek bilançosunu açıkladı](https://www.bloomberght.com/is-bankasi-ikinci-ceyrek-bilancosunu-acikladi-2357995) |  |
| 91 | AEFES | body | correct | [Ocak'ta yabancının en çok alım-satım yaptığı hisseler](https://www.bloomberght.com/ocak-ta-yabancinin-en-cok-alim-satim-yaptigi-hisseler-3741447) |  |
| 92 | SASA | body | correct | [Erdemoğlu Holding Sasa'da bu kez hisse alımı yaptı](https://www.bloomberght.com/erdemoglu-holding-sasa-da-bu-kez-hisse-alimi-yapti-2344298) |  |
| 93 | VESTL | title | correct | [Vestel'den borç yapılandırma haberlerine ilişkin açıklama](https://www.bloomberght.com/vestel-den-borc-yapilandirma-haberlerine-iliskin-aciklama-3770125) |  |
| 94 | ISCTR | title | correct | [İş Bankası yurt dışı tahvil ihracı için bankaları yetkilendirdi](https://www.bloomberght.com/is-bankasi-yurtdisi-tahvil-ihraci-icin-bankalari-yetkilendirdi-3757661) |  |
| 95 | OYAKC | body | correct | [Rekabet Kurulu'ndan 17 çimento ve beton şirketine soruşturma](https://www.bloomberght.com/rekabet-kurulu-ndan-17-cimento-sirketine-sorusturma-2341665) |  |
| 96 | KCHOL | body | correct | [Koç: Yapı Kredi için iddialarda belirtilen nitelikte bir görüşme söz konusu değil](https://www.bloomberght.com/koc-holding-yapi-kredi-de-iddialarda-belirtilen-nitelikte-bir-gorusme-soz-konusu-degil-3735937) |  |
| 97 | GARAN | body | correct | [Morgan Stanley, Türk bankalarında hedef düşürdü](https://www.bloomberght.com/morgan-turk-bankalarinda-hedef-dusurdu-2357038) |  |
| 98 | HEKTS | body | correct | [MSCI Türkiye endekslerinde değişiklik yapıldı](https://www.bloomberght.com/msci-turkiye-endekslerinde-degisiklik-yapildi-2347494) |  |
| 99 | AKBNK | title | correct | [Akbank GM Gür, 2024’te de istikrar kazandırıcı adımların devamını bekliyor](https://www.bloomberght.com/akbank-gm-gur-2024te-de-istikrar-kazandirici-adimlarin-devamini-bekliyor-2344473) |  |
| 100 | CIMSA | body | correct | [Sabancı 3. çeyrek sonuçlarını açıkladı, '5 yılda 20 milyar dolarlık Sabancı' hedefi koydu](https://www.bloomberght.com/sabanci-3-ceyrek-sonuclarini-acikladi-3733971) |  |

## Round 2 sample

| # | Stock | Match | Class | Headline (original Turkish) | Note |
|---|---|---|---|---|---|
| 1 | AKBNK | body | correct | [JPMorgan dört Türk bankasını negatif izlemeye aldı](https://www.bloomberght.com/jpmorgan-dort-turk-bankasini-negatif-izlemeye-aldi-2346084) |  |
| 2 | ASELS | title | correct | [Aselsan/Akyol: Yüksek teknolojiye odaklanacağız](https://www.bloomberght.com/aselsanakyol-yuksek-teknolojiye-odaklanacagiz-2343401) |  |
| 3 | AKBNK | title | correct | [Akbank'tan 600 milyon dolarlık tahvil ihracı](https://www.bloomberght.com/akbank-tan-600-milyon-dolarlik-tahvil-ihraci-3769182) |  |
| 4 | YKBNK | body | weak | [SPK'dan kripto kararı](https://www.bloomberght.com/spk-dan-kripto-karari-3772994) | new platform of the subsidiary Yapı Kredi Blokzincir |
| 5 | ISCTR | title | correct | [İş Bankası'nın net kârı tahminleri aştı / Son dakika ekonomi haberleri](https://www.bloomberght.com/is-bankasi-nin-kri-2024-un-son-ceyreginde-tahminleri-asti-3741489) |  |
| 6 | ISCTR | title | correct | [İş Bankası'nda üst düzey atamalar](https://www.bloomberght.com/is-bankasi-nda-ust-duzey-atamalar-3771884) |  |
| 7 | HALKB | title | correct | [Halkbank: ABD Mahkemesi’nin onayı ile dava tamamen sona erecek](https://www.bloomberght.com/halkbank-abd-mahkemesinin-onayi-ile-dava-tamamen-sona-erecek-3779618) |  |
| 8 | GARAN | title | correct | [Garanti BBVA 2025 yılı son çeyrek bilançosunu açıkladı](https://www.bloomberght.com/garanti-bbva-2025-yili-son-ceyrek-bilancosunu-acikladi-3768292) |  |
| 9 | CIMSA | title | correct | [Çimsa'ya yeşil enerji kredisi](https://www.bloomberght.com/cimsa-ya-yesil-enerji-kredisi-3733640) |  |
| 10 | PGSUS | title | correct | [Pegasus, Orta Doğu ülkelerine uçuş iptallerini uzattı](https://www.bloomberght.com/pegasus-orta-dogu-ulkelerine-ucus-iptallerini-uzatti-3773626) |  |
| 11 | TSKB | code | weak | [Odine Solutions halka arz büyüklüğü 1,33 milyar TL oldu](https://www.bloomberght.com/odine-solutions-halka-arz-buyuklugu-1-33-milyar-tl-oldu-2349547) | KAP filing as the IPO intermediary |
| 12 | AKBNK | title | correct | [Akbank sendikasyon temin etti](https://www.bloomberght.com/akbank-sendikasyon-temin-etti-2351139) |  |
| 13 | YKBNK | title | correct | [Yapı Kredi eurobond için yeniden ihraca çıktı](https://www.bloomberght.com/yapi-kredi-eurobond-icin-yeniden-ihraca-cikti-2342364) |  |
| 14 | ISCTR | body | weak | [Küresel ve ulusal dijital finans ekosistemi İstanbul’da buluştu](https://www.bloomberght.com/kuresel-ve-ulusal-dijital-finans-ekosistemi-istanbulda-bulustu-2351372) | fintech award |
| 15 | AKBNK | body | correct | [BofA'dan Türk bankacılık analizi](https://www.bloomberght.com/bofa-dan-turk-bankacilik-analizi-2362762) |  |
| 16 | VESTL | title | correct | [Bloomberg: Vestel borç yapılandırmasında ileri aşamada](https://www.bloomberght.com/bloomberg-vestel-borc-yapilandirmasinda-ileri-asamada-3770088) |  |
| 17 | SASA | code | correct | [Sasa'da 25 milyar dolarlık yatırım planı](https://www.bloomberght.com/sasa-da-25-milyar-dolarlik-yatirim-plani-3755681) |  |
| 18 | SELEC | code | correct | [Üç hisseye kredili işlem yasağı](https://www.bloomberght.com/uc-hisseye-kredili-islem-yasagi-2359918) |  |
| 19 | TOASO | title | correct | [Tofaş 3.çeyrekte 1,2 milyar TL net kâr açıkladı / Son dakika ekonomi haberleri](https://www.bloomberght.com/tofas-3ceyrekte-1-2-milyar-tl-net-kr-acikladi-3760698) |  |
| 20 | MGROS | title | correct | [Migros'tan kâr payı dağıtım kararı](https://www.bloomberght.com/migros-tan-kr-payi-dagitim-karari-3746429) |  |
| 21 | ASELS | title | correct | [Aselsan ile Havelsan arasında mutabakat zaptı](https://www.bloomberght.com/aselsan-ile-havelsan-arasinda-mutabakat-zapti-imzalandi-2346101) |  |
| 22 | AKBNK | title | correct | [Akbank'tan 2024'ün son çeyreğinde 9,2 milyar TL net kâr](https://www.bloomberght.com/akbank-tan-2024-un-son-ceyreginde-9-2-milyar-tl-net-kr-3740493) |  |
| 23 | ASELS | title | correct | [Aselsan, radar üretim kapasitesini üç katına çıkaracak](https://www.bloomberght.com/aselsan-radar-uretim-kapasitesini-uc-katina-cikaracak-3739230) |  |
| 24 | OYAKC | title | correct | [Oyak Çimento'dan bedelsiz sermaye artırımı](https://www.bloomberght.com/oyak-cimento-dan-bedelsiz-sermaye-artirimi-2353277) |  |
| 25 | GARAN | body | correct | [BBVA, Garanti'nin satışı haberlerini yalanladı](https://www.bloomberght.com/bbva-garanti-nin-satisi-haberlerini-yalanladi-2352890) |  |
| 26 | CIMSA | title | correct | [Çimsa ABD'deki yatırımını devreye aldı](https://www.bloomberght.com/cimsa-abd-deki-yatirim-devreye-aldi-3759143) |  |
| 27 | HALKB | title | correct | [Halkbank’ın üç aylık net kârı beklentiyi aştı](https://www.bloomberght.com/halkbankin-uc-aylik-net-kri-beklentiyi-asti-3777194) |  |
| 28 | ASELS | title | correct | [Aselsan ile Roketsan arasında sözleşme değişikliği](https://www.bloomberght.com/aselsan-ile-roketsan-arasinda-sozlesme-degisikligi-2356060) |  |
| 29 | YKBNK | body | correct | [Borsada yeni zirve](https://www.bloomberght.com/borsada-yeni-zirve-2350764) |  |
| 30 | TTKOM | title | correct | [Türk Telekom: Bizim altyapımız Türkiye'nin altyapısıdır](https://www.bloomberght.com/turk-telekom-bizim-altyapimizturkiye-nin-altyapisidir-3755903) |  |
| 31 | ENKAI | body | correct | [Enka işti̇raki, bir ABD şirketiyle 527,5 milyon dolarlık sözleşme imzaladı](https://www.bloomberght.com/enka-istiraki-bir-abd-sirketiyle-527-5-milyon-dolarlik-sozlesme-imzaladi-3749186) |  |
| 32 | TSKB | title | correct | [TSKB'den 300 milyon dolarlık tahvil ihracı](https://www.bloomberght.com/tskb-den-300-milyon-dolarlik-tahvil-ihraci-3781476) |  |
| 33 | SAHOL | title | correct | [Sabancı/Cenk Alper: İşlerimizi doğayla uyumlu hale getirmeliyiz](https://www.bloomberght.com/sabancicenk-alper-islerimizi-dogayla-uyumlu-hale-getirmeliyiz-3740012) |  |
| 34 | THYAO | title | correct | [THY’den Boeing siparişi](https://www.bloomberght.com/thyden-boeing-siparisi-3758005) |  |
| 35 | TATGD | title | correct | [Tat Gıda'nın satışı tamamlandı](https://www.bloomberght.com/tat-gida-nin-satisi-tamamlandi-2347880) |  |
| 36 | ENJSA | title | correct | [Enerjisa Enerji üst yönetiminde görev değişimi](https://www.bloomberght.com/enerjisa-enerji-ust-yonetiminde-gorev-degisimi-3789787) |  |
| 37 | YKBNK | body | correct | [Koç Holding'ten 2025 yılı 4. çeyrekte 7 milyar TL net kâr](https://www.bloomberght.com/koc-holding-ten-2025-yili-4-ceyrekte-7-milyar-tl-net-kr-3768891) |  |
| 38 | CCOLA | body | weak | [Anadolu Efes’te üst düzey iki atama](https://www.bloomberght.com/anadolu-efeste-ust-duzey-iki-atama-2348568) | the appointed executive previously worked at Coca-Cola İçecek |
| 39 | GARAN | title | correct | [Garanti Bankası'nın net kârı beklentileri aştı](https://www.bloomberght.com/garanti-bankasi-nin-net-kri-beklentileri-asti-3776188) |  |
| 40 | KCHOL | body | wrong | [27 Türk dünya milyarderler liginde](https://www.bloomberght.com/27-turk-dunya-milyarderler-liginde-2350487) | billionaires list; title 'Koç Holding board member' |
| 41 | HALKB | title | correct | [Halkbank 88. yılını kutluyor](https://www.bloomberght.com/halkbank-88-yilini-kutluyor-3778390) |  |
| 42 | BIMAS | body | correct | [Borsada şirketlerin geri alımları sürüyor](https://www.bloomberght.com/borsada-sirketlerin-geri-alimlari-suruyor-3744818) |  |
| 43 | PGSUS | title | correct | [Pegasus'ta bilet fiyatlamada yapay zeka kullanımı](https://www.bloomberght.com/pegasus-ta-bilet-fiyatlamada-yapay-zeka-kullanimi-3737638) |  |
| 44 | HALKB | title | correct | [Halkbank’ın esnaf ve sanatkârlara yönelik kredilerin faiz indiriminde değişiklik](https://www.bloomberght.com/halkbankin-esnaf-ve-sanatkrlara-yonelik-kredilerin-faiz-indiriminde-degisiklik-3786539) |  |
| 45 | BIMAS | body | correct | [HSBC Türk perakende hisselerinde hedeflerini güncelledi](https://www.bloomberght.com/hsbc-turk-perakende-hisselerinde-hedeflerini-guncelledi-3767057) |  |
| 46 | SISE | title | correct | [Şişecam Yönetim Kurulu Başkanı Adnan Bali oldu](https://www.bloomberght.com/sisecam-yonetim-kurulu-baskani-adnan-bali-oldu-2355508) |  |
| 47 | ISCTR | title | correct | [İş Bankası "Türkiye'nin en değerli banka markası" seçildi](https://www.bloomberght.com/is-bankasi-turkiye-nin-en-degerli-banka-markasi-secildi-2348976) |  |
| 48 | ISCTR | title | correct | [İş Bankası’ndan kurucu intifa senedi açıklaması / Son dakika ekonomi haberleri](https://www.bloomberght.com/is-bankasindan-kurucu-intifa-senedi-aciklamasi-3745156) |  |
| 49 | BIMAS | body | correct | [Türkiye'de 120 milyar doları aşan gıda perakendeciliğinin röntgeni](https://www.bloomberght.com/turkiye-de-120-milyar-dolari-asan-gida-perakendeciliginin-rontgeni-3782601) |  |
| 50 | GLYHO | title | correct | [Global Yatırım Holding hisse geri alım programı başlattı](https://www.bloomberght.com/global-yatirim-holding-hisse-geri-alim-programi-baslatti-3744720) |  |
| 51 | VAKBN | title | correct | [Vakıfbank, yurt dışından yeni kaynak temin etti](https://www.bloomberght.com/vakifbank-yurt-disindan-yeni-kaynak-temin-etti-2348892) |  |
| 52 | TUPRS | body | correct | [Borsada jeopolitik baskı](https://www.bloomberght.com/borsada-jeopolitik-baski-2340198) |  |
| 53 | TSKB | code | wrong | [Hedef Portföy’e yeni Genel Müdür atandı / Son dakika ekonomi haberleri](https://www.bloomberght.com/hedef-portfoye-yeni-genel-mudur-atandi-3762159) | biography: former TSKB CFO |
| 54 | SISE | title | correct | [Şişecam'ın kum hazırlama tesisinin çelik işlerini Karçel üstlendi](https://www.bloomberght.com/sisecam-in-kum-hazirlama-tesisinin-celik-islerini-karcel-ustlendi-2357212) |  |
| 55 | SAHOL | title | correct | [Sabancı Holding CEO'su Zaimler: Yurt dışındaki fırsatlara bakacağız](https://www.bloomberght.com/sabanci-holding-ceo-su-zaimler-yurt-disindaki-firsatlara-bakacagiz-3766888) |  |
| 56 | KRDMD | body | correct | [MSCI Türkiye endeksinde güncelleme](https://www.bloomberght.com/msci-turkiye-endeksinde-guncelleme-3760912) |  |
| 57 | ARCLK | body | correct | [Ford Otosan Koçfinans'ı bünyesine kattı](https://www.bloomberght.com/ford-otosan-kocfinans-i-bunyesine-katti-3781665) |  |
| 58 | KCHOL | title | correct | [Koç Holding Kemer Medical Center’ın yüzde 80’ini satın aldı](https://www.bloomberght.com/koc-holding-kemer-medical-centerin-yuzde-80ini-satin-aldi-2350157) |  |
| 59 | ARCLK | title | correct | [Arçelik ve Yapı Kredi Leasing'ten güneş enerjisi işbirliği](https://www.bloomberght.com/arcelik-ve-yapi-kredi-leasing-ten-gunes-enerjisi-isbirligi-3735679) |  |
| 60 | YKBNK | title | correct | [Yapı Kredi'den 500 milyon dolarlık tahvil ihracı](https://www.bloomberght.com/yapi-kredi-den-500-milyon-dolarlik-tahvil-ihraci-3763165) |  |
| 61 | ASELS | title | correct | [Türk Telekom ve Aselsan'dan stratejik işbirliği](https://www.bloomberght.com/turk-telekom-ve-aselsan-dan-stratejik-isbirligi-3778008) |  |
| 62 | MGROS | title | correct | [Migros’ta satışlar arttı, kârlılık düştü](https://www.bloomberght.com/migrosta-satislar-artti-krlilik-dustu-2353531) |  |
| 63 | THYAO | title | correct | [Fitch'ten THY yorumu: Latin Amerika ağ erişimi güçlenecek](https://www.bloomberght.com/fitch-ten-thy-yorumu-latin-amerika-ag-erisimi-guclenecek-3756738) |  |
| 64 | KRDMD | title | correct | [Borsada gong Kardemir Çelik için çaldı](https://www.bloomberght.com/borsada-gong-kardemir-celik-icin-caldi-3784389) |  |
| 65 | SOKM | title | correct | [Şok Market, İstegelsin'i satın aldı](https://www.bloomberght.com/sok-market-istegelsin-i-satin-aldi-2351120) |  |
| 66 | MIATK | body | correct | [Borsa İstanbul’da pazar kriterleri değişti, endeksler yeniden şekillendi](https://www.bloomberght.com/borsa-istanbulda-pazar-kriterleri-degisti-endeksler-yeniden-sekillendi-3789023) |  |
| 67 | GARAN | title | correct | [Garanti BBVA'dan kripto yasası yorumu](https://www.bloomberght.com/garanti-bbva-dan-kripto-yasasi-yorumu-2355532) |  |
| 68 | MPARK | title | correct | [MLP Sağlık'ta yabancı ortak hisselerini sattı](https://www.bloomberght.com/mlp-saglik-ta-yabanci-ortak-hisselerini-satti-3754007) |  |
| 69 | GARAN | title | correct | [Garanti BBVA'da temettü teklifi açıklandı](https://www.bloomberght.com/garanti-bbva-da-temettu-teklifi-aciklandi-2349123) |  |
| 70 | ASELS | title | correct | [Aselsan, 42 milyon dolarlık ihracat sözleşmesi imzaladı](https://www.bloomberght.com/aselsan-42-milyon-dolarlik-ihracat-sozlesmesi-imzaladi-3738159) |  |
| 71 | ASELS | title | correct | [Aselsan'dan 26,2 milyon dolarlık sözleşme](https://www.bloomberght.com/aselsan-dan-26-2-milyon-dolarlik-sozlesme-2361558) |  |
| 72 | TTRAK | title | correct | [Türk Traktör'den satın alma](https://www.bloomberght.com/turk-traktor-den-satin-alma-3733380) |  |
| 73 | ISCTR | title | correct | [İş Bankası Kıbrıs’ta 70. yılında](https://www.bloomberght.com/is-bankasi-kibrista-70-yilinda-3746923) |  |
| 74 | ULKER | body | weak | [Yıldız Holding'de yeni dönem](https://www.bloomberght.com/yildiz-holding-de-yeni-donem-3747296) | chair change at the parent Yıldız Holding, filed on KAP via Ülker Bisküvi |
| 75 | ISCTR | body | weak | ["KOBİ’lerin likiditeleri yoğun bir şekilde bozuldu"](https://www.bloomberght.com/kobilerin-likiditeleri-yogun-bir-sekilde-bozuldu-3762102) | an İş Bankası deputy CEO's comment on SME liquidity |
| 76 | THYAO | title | correct | [THY'nin New York uçuşlarına olumsuz hava engeli](https://www.bloomberght.com/thy-nin-new-york-ucuslarina-olumsuz-hava-engeli-3769832) |  |
| 77 | HALKB | body | weak | [Kredi için 99,4 milyon liralık BES fonu teminat gösterildi](https://www.bloomberght.com/kredi-icin-99-4-milyon-liralik-bes-fonu-teminat-gosterildi-2360597) | among the banks requesting loans collateralised by pension funds |
| 78 | MIATK | title | correct | [MİA Teknoloji'den ABD yatırımı değerlendirmesi](https://www.bloomberght.com/mia-teknoloji-abd-de-hisse-satisiyla-yurt-disi-yatirimi-yapacak-2341194) |  |
| 79 | ENJSA | title | correct | [Enerjisa'dan rekor tahvil ihracı](https://www.bloomberght.com/enerjisa-dan-rekor-tahvil-ihraci-3741437) |  |
| 80 | KCHOL | body | correct | [Ömer Koç: 2025'in riskleri tedarik zinciri ve korumacı tedbirler olacak](https://www.bloomberght.com/omer-koc-2025-in-riskleri-tedarik-zinciri-ve-korumaci-tedbirler-olacak-3735896) |  |
| 81 | EKGYO | title | correct | [Emlak Konut'tan indirim kampanyası](https://www.bloomberght.com/emlak-konut-tan-indirim-kampanyasi-2353832) |  |
| 82 | ASELS | title | correct | [ASELSAN'dan 54 milyon dolarlık sözleşme](https://www.bloomberght.com/aselsan-dan-54-milyon-dolarlik-sozlesme-3742956) |  |
| 83 | TAVHL | body | correct | [SPK’dan 3 şirketin halka arz başvurusuna onay](https://www.bloomberght.com/spkdan-3-sirketin-halka-arz-basvurusunu-onay-2342544) |  |
| 84 | KCHOL | title | correct | [Koç Holding'ten kredi notu açıklaması](https://www.bloomberght.com/koc-holding-ten-kredi-notu-aciklamasi-2357314) |  |
| 85 | BIMAS | body | correct | [JPMorgan 3 yıl sonra bir Türk şirketini 'Top 10' listesine ekledi](https://www.bloomberght.com/jpmorgan-3-yil-sonra-bir-turk-sirketini-top-10-listesine-ekledi-2339575) |  |
| 86 | CIMSA | body | correct | [Sabancı CEO'su Alper: 'Yatırım yap' diyen bir bilançomuz var / Son dakika ekonomi haberleri](https://www.bloomberght.com/sabanci-ceo-su-alper-yatirim-yap-diyen-bir-bilancomuz-var-3743586) |  |
| 87 | KRDMD | title | correct | [Kardemir'de yeni yönetim belirlendi](https://www.bloomberght.com/kardemir-de-yeni-yonetim-belirlendi-2340589) |  |
| 88 | EKGYO | title | correct | [Emlak Konut ile Suudi Arabistan'ın ulusal konut şirket arasında anlaşma](https://www.bloomberght.com/emlak-konut-ile-suudi-arabistan-in-ulusal-konut-sirket-arasinda-anlasma-3736047) |  |
| 89 | THYAO | body | correct | [Erdoğan ve Trump Beyaz Saray’da görüşecek](https://www.bloomberght.com/erdogan-ve-trump-beyaz-sarayda-gorusecek-3757633) |  |
| 90 | VAKBN | body | wrong | [“İrade Bizim, Zafer Bizim” sergisi ziyaretçileriyle buluştu](https://www.bloomberght.com/irade-bizim-zafer-bizim-sergisi-ziyaretcileriyle-bulustu-3783247) | venue name: 'VakıfBank Sanat Galerisi' |
| 91 | TUPRS | title | correct | [Tüpraş’tan sermaye tavanı artırımı başvurusu](https://www.bloomberght.com/tuprastan-sermaye-tavani-artirimi-basvurusu-3740248) |  |
| 92 | ENJSA | title | correct | [EBRD'den Enerjisa'ya 100 milyon dolarlık destek](https://www.bloomberght.com/ebrd-denenerjisa-ya-100-milyon-dolarlik-destek-2346585) |  |
| 93 | TAVHL | body | correct | [Rekabet Kurulu bazı devralma işlemlerini onayladı](https://www.bloomberght.com/rekabet-kurulu-bazi-devralma-islemlerini-onayladi-2353829) |  |
| 94 | ISCTR | title | correct | [İş Bankası'ndan dijital tahvil ihracı](https://www.bloomberght.com/is-bankasi-ndan-dijital-tahvil-ihraci-3751700) |  |
| 95 | KRDMD | title | correct | [Goldman Sachs Kardemir'de yine pay artırdı](https://www.bloomberght.com/goldman-sachs-kardemir-de-yine-pay-artirdi-3791051) |  |
| 96 | VAKBN | title | correct | [Vakıfbank’tan 2. çeyrekte 7,2 milyar lira net kâr](https://www.bloomberght.com/vakifbanktan-2-ceyrekte-7-2-milyar-lira-net-kr-2358115) |  |
| 97 | AEFES | title | correct | [Anadolu Efes'ten tarımsal ekonomiye 1.3 milyar TL'lik katkı](https://www.bloomberght.com/anadolu-efes-ten-tarimsal-ekonomiye-13-milyar-tl-lik-katki-2357172) |  |
| 98 | ALBRK | body | correct | [Rekabet'ten bankalara soruşturma](https://www.bloomberght.com/rekabet-ten-bankalara-sorusturma-3769945) |  |
| 99 | KRDMD | title | correct | [Kardemir ray ihalesi kazandı](https://www.bloomberght.com/kardemir-ray-ihalesi-kazandi-2362210) |  |
| 100 | TUPRS | body | correct | [7 başlıkta geçen hafta](https://www.bloomberght.com/7-baslikta-gecen-hafta-3760578) |  |
