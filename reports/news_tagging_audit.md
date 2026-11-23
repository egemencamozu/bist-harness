# Haber etiketleme kesinlik denetimi (2026-11-23)

Kaynak: Bloomberg HT arşivi, donmuş snapshot `data/raw/news_bloomberght/2026-11-20` (40.780 makale). Etiketleyici: `src/bistharness/data/ingest/news.py` + `config/news.yaml` (deterministik kurallar, LLM yok). Birim: (makale, hisse) çifti. Değerlendirme: Claude, başlık + eşleşen metin parçası okunarak; kullanıcı tarafından tekrar kontrol edilebilir (aşağıda her satır URL'siyle).

**Sınıflar.** *doğru* = şirket haberin konusu ya da habere özgü somut bilgi (anlaşma, not, pay, sonuç, işlem tedbiri); *zayıf* = şirket gerçekten geçiyor ama yan rolde (halka arz aracısı, ödül, iştirak, yönetici yorumu); *yanlış* = o şirket değil (aynı kelimeli başka varlık, piyasa terimi, etkinlik/mekân adı, kazıma hatası) ya da yalnız bir kişinin unvanı.

**Yöntem (yanlılığı önlemek için iki tur).** Tur 1 = ilk kural seti + 66 yeni hisse, rastgele 100 çift (tohum 2026); bulunan sistematik hatalar düzeltildi (dışlama listeleri + başka haberin başlığının metne kopyalanması kuralı). Tur 2 = düzeltilmiş kurallar, tur 1 ile ÇAKIŞMAYAN yeni rastgele 100 çift (tohum 4242), sonuç görülmeden çekildi = tarafsız ölçüm. Tur 2'de görülen hatalar için kural EKLENMEDİ (aksi halde ölçüm yine yanlı olurdu); bilinen sınırlar olarak listelenir.


## Tur 1 (düzeltmeden önce; düzeltmeler bu örnekten tasarlandı)

- doğru 92, zayıf 3, yanlış 5 (n=100)
- katı kesinlik (yalnız doğru): %92 (%95 GA %85.0–%95.9)
- geniş kesinlik (doğru + zayıf = şirket gerçekten geçiyor): %95 (%95 GA %88.8–%97.8)
- başlık eşleşmesi: 71/72 doğru; metin/kod eşleşmesi: 21/28 doğru, 3 zayıf, 4 yanlış

## Tur 2 (düzeltmeden sonra, tarafsız)

- doğru 90, zayıf 7, yanlış 3 (n=100)
- katı kesinlik (yalnız doğru): %90 (%95 GA %82.6–%94.5)
- geniş kesinlik (doğru + zayıf = şirket gerçekten geçiyor): %97 (%95 GA %91.5–%99.0)
- başlık eşleşmesi: 67/67 doğru; metin/kod eşleşmesi: 23/33 doğru, 7 zayıf, 3 yanlış

## Sonuç ve sınırlar

- Başlık eşleşmeleri: tur 1'de 71/72 (tek hata "Yapı Kredi Yatırım: …" piyasa notu, kurala bağlandı), tur 2'de
  67/67 doğru. Kalan hatalar metin içi eşleşmelerde (tur 2: 33'te 3 yanlış, 7 zayıf).
- Tur 1'in sistematik hataları kurala bağlandı: 'Türkiye Sigorta Birliği', 'Türkiye sigorta piyasası/sektörü' (TURSG değil), 'Enerjisa Üretim' (borsada değil), 'Yapı Kredi Yatırım/Portföy' ve 'Garanti BBVA Yatırım/Portföy' araştırma notları, 'Albaraka Zirveleri' etkinlik adı; başka bir haberin başlığı metinde aynen geçiyorsa (kenar kutusu / 'geçen hafta' özeti) o kısım sayılmaz (arşivde ~32 makalede aynı Vestel başlığı vardı).
- Tur 2'de kalan hata türleri (kurala bağlanmadı): kişinin unvanı ('Koç Holding YK üyesi'), biyografi, mekân adı ('VakıfBank Sanat Galerisi').
- Etki: haber bu projede yalnız bağlamsal kanıttır (son 30 günün etiketli haber sayısı); karar politikası haberi kullanmaz, haber içindeki sayılar kanıt olmaz. Bir yanlış etiket hiçbir sayıyı/eylemi değiştirmez.
- Ölçülmeyen: duyarlılık (kaçırılan haberler). Tek geçişli metin anmaları (`min_body_mentions: 2`) bilinçli olarak sayılmaz; kısa adlar ("Koç'tan") başlıkta tanınmayabilir.
- Kapsam: 96 hissenin 83'ünde en az bir haber; hiç haber olmayanlar: ALGYO, ARDYZ, AYEN, BERA, CEMTS, DEVA, ECZYT, EGEEN, GOODY, KATMR, LOGO, NUHCM, ODAS.
- Kaynak seçimi: yalnız Bloomberg HT. FinTreX arşivindeki genel gazeteler (Sabah, Cumhuriyet, Habertürk, Sözcü, Takvim) ve Telegram kanalları (BPT Finans, Para Ajansı, …) ders projesinde kullanılmadı (genel gündem → daha çok yanlış eşleşme; aynı haber 5–6 sitede → tekilleştirme gerekir; Telegram'da tam metin yok). TÜBİTAK/FinTreX aşamasına bırakıldı.


## Tur 1 örneği

| # | Hisse | Eşleşme | Sınıf | Başlık | Not |
|---|---|---|---|---|---|
| 1 | ASELS | title | doğru | [Aselsan'dan NATO ile stratejik işbirliği](https://www.bloomberght.com/aselsan-dan-nato-ile-stratejik-isbirligi-3782104) |  |
| 2 | EKGYO | body | doğru | [Gayrimenkul sertifikasına yaklaşık iki katlık talep](https://www.bloomberght.com/gayrimenkul-sertifikasina-yaklasik-iki-katlik-talep-3754553) |  |
| 3 | MGROS | title | doğru | [Migros ilk çeyrekte 51 mağaza açtı; mağaza sayısı 3 bin 812'ye ulaştı](https://www.bloomberght.com/migros-ilk-ceyrekte-51-magaza-acti-magaza-sayisi-3-bin-812-ye-ulasti-3776751) |  |
| 4 | AKBNK | body | doğru | [Morgan Stanley Türk bankalarını mercek altına aldı](https://www.bloomberght.com/morgan-stanley-turk-bankalarini-mercek-altina-aldi-3786582) |  |
| 5 | SISE | title | doğru | [Şişecam UK, dolar tahvil yatırımcı görüşmeleri için yetki verdi / Son dakika ekonomi haberleri](https://www.bloomberght.com/sisecam-uk-dolar-tahvil-yatirimci-gorusmeleri-icin-yetki-verdi-3766016) |  |
| 6 | YKBNK | title | doğru | [Yapı Kredi'de sermaye benzeri borçlanma hazırlığı](https://www.bloomberght.com/yapi-kredi-de-sermaye-benzeri-borclanma-hazirligi-3763041) |  |
| 7 | ASELS | title | doğru | [Aselsan'dan 109,7 milyon dolarlık sözleşme](https://www.bloomberght.com/aselsan-dan-109-7-milyon-dolarlik-sozlesme-2355802) |  |
| 8 | ISCTR | title | doğru | [İş Bankası ve TSKB'den güneşe 100 milyon euroluk finansman](https://www.bloomberght.com/yerli-teknolojiye-100-milyon-euroluk-ortak-finansman-3768838) |  |
| 9 | TSKB | code | zayıf | [Dünya Bankası'ndan Türkiye'ye ek 18 milyar dolarlık finansman](https://www.bloomberght.com/dunya-bankasi-ndan-turkiye-ye-ek-18-milyar-dolarlik-finansman-2354262) | TSKB'nin düzenlediği etkinlikte Dünya Bankası konuşması |
| 10 | VESTL | body | doğru | [Zorlu Grubu'ndan finansal yeniden yapılandırma başvurusu](https://www.bloomberght.com/zorlu-grubu-ndan-finansal-yeniden-yapilandirma-basvurusu-3781350) |  |
| 11 | SAHOL | title | doğru | ["Sabancı'nın dünyanın 18 farklı ülkesinde ayak izi bulunuyor"](https://www.bloomberght.com/sabanci-holding-in-turkiye-onceligi-devam-edecek-3767471) |  |
| 12 | SISE | title | doğru | [Şişecam 2025 yılını 9,9 milyar TL net kâr ile tamamladı](https://www.bloomberght.com/sisecam-2025-yilini-9-9-milyar-tl-net-kr-ile-tamamladi-3769331) |  |
| 13 | PGSUS | title | doğru | [Pegasus ve THY uçakları geri dönüyor](https://www.bloomberght.com/pegasus-ve-thy-ucaklari-geri-donuyor-2350951) |  |
| 14 | ISCTR | title | doğru | [İş Bankası/Aran: 2026 Mayıs ayında normalleşme olur](https://www.bloomberght.com/is-bankasiaran-2026-mayis-ayinda-normallesme-olur-3754664) |  |
| 15 | TCELL | title | doğru | [Turkcell Genel Müdürlüğü'ne Ali Taha Koç atandı](https://www.bloomberght.com/turkcell-genel-mudurlugu-ne-ali-taha-koc-atandi-2340083) |  |
| 16 | ASELS | title | doğru | [Roketsan'dan Aselsan'a yeni sipariş](https://www.bloomberght.com/roketsan-dan-aselsan-a-yeni-siparis-2354813) |  |
| 17 | THYAO | title | doğru | [THY ve Pegasus İsrail uçuşlarına ara verdi](https://www.bloomberght.com/pegasus-israil-ucuslarina-ara-verdi-2339892) |  |
| 18 | VESTL | title | doğru | [Vestel, Çinli yayın platformunda hisse alıyor](https://www.bloomberght.com/vestel-cinli-yayin-platformunda-hisse-aliyor-2360514) |  |
| 19 | TSKB | title | doğru | [TSKB, Aksa Yenilenebilir Enerji ile yeni bir kredi anlaşmasına imza attı](https://www.bloomberght.com/tskb-aksa-yenilenebilir-enerji-ile-yeni-bir-kredi-anlasmasina-imza-atti-3753561) |  |
| 20 | TTRAK | title | doğru | [Türk Traktör'den yeni yatırım kararı](https://www.bloomberght.com/turk-traktor-den-yeni-yatirim-karari-3736282) |  |
| 21 | TTKOM | title | doğru | [Türk Telekom'dan beklenti üstü net kâr](https://www.bloomberght.com/turk-telekom-dan-beklenti-ustu-net-kr-3776875) |  |
| 22 | KORDS | title | doğru | [Kordsa'nın yeni CEO'su belli oldu](https://www.bloomberght.com/kordsa-nin-yeni-ceo-su-belli-oldu-3749134) |  |
| 23 | TUPRS | title | doğru | [Tüpraş İstanbul Havalimanı’na 1,8 milyon ton jet yakıtı satacak](https://www.bloomberght.com/tupras-istanbul-havalimanina-1-8-milyon-ton-jet-yakiti-satacak-2363221) |  |
| 24 | TTKOM | title | doğru | [Türk Telekom’dan enerjiden yapay zekaya büyüme hamlesi](https://www.bloomberght.com/turk-telekomdan-enerjiden-yapay-zekaya-buyume-hamlesi-3789696) |  |
| 25 | SAHOL | title | doğru | [Sabancı'dan ABD'de güneş enerjisi yatırımı](https://www.bloomberght.com/sabanci-dan-abd-de-gunes-enerjisi-yatirimi-3752301) |  |
| 26 | GARAN | body | doğru | [JPMorgan dört Türk bankasını negatif izlemeye aldı](https://www.bloomberght.com/jpmorgan-dort-turk-bankasini-negatif-izlemeye-aldi-2346084) |  |
| 27 | ENJSA | title | doğru | [Enerjisa'dan ikinci çeyrekte 512,3 milyon TL net kâr](https://www.bloomberght.com/enerjisa-dan-ikinci-ceyrekte-512-3-milyon-tl-net-kr-3754602) |  |
| 28 | EKGYO | body | zayıf | [15 soruda "Yarısı Bizden" kampanyası](https://www.bloomberght.com/15-soruda-yarisi-bizden-kampanyasi-3734286) | kampanya konutlarını TOKİ ya da Emlak Konut üstleniyor |
| 29 | SASA | title | doğru | [SASA'dan hisse geri alım kararı](https://www.bloomberght.com/sasa-dan-hisse-geri-alim-karari-2359100) |  |
| 30 | ARCLK | title | doğru | [Arçelik'ten Bangladeş'te üretim açıklaması](https://www.bloomberght.com/arcelik-ten-banglades-te-uretim-aciklamasi-2361819) |  |
| 31 | ASELS | title | doğru | [Aselsan'dan 35 milyon dolarlık sözleşme](https://www.bloomberght.com/aselsan-dan-35-milyon-dolarlik-sozlesme-2350134) |  |
| 32 | ISCTR | body | doğru | [Galataport bankalarla yapılandırma anlaşması imzaladı](https://www.bloomberght.com/galataport-bankalarla-yapilandirma-anlasmasi-imzaladi-3737169) |  |
| 33 | ULKER | title | doğru | [Ülker Bisküvi 5 yıl vadeli 250 milyon dolar sendikasyon kredisi sağladı](https://www.bloomberght.com/ulker-biskuvi-5-yil-vadeli-250-milyon-dolar-sendikasyon-kredisi-sagladi-3758608) |  |
| 34 | ASELS | title | doğru | [Aselsan, BMC ile yeni sözleşme imzaladı](https://www.bloomberght.com/aselsan-bmc-ile-yeni-sozlesme-imzaladi-3742401) |  |
| 35 | KRDMD | title | doğru | [Kardemir/Demir: Rüzgar ve jeotermalde büyük yatırımlara başlayacağız](https://www.bloomberght.com/kardemirdemir-ruzgar-ve-jeotermalde-buyuk-yatirimlara-baslayacagiz-2348698) |  |
| 36 | HALKB | body | doğru | [7 başlıkla geçen hafta](https://www.bloomberght.com/7-baslikla-gecen-hafta-3780726) |  |
| 37 | ULKER | title | doğru | [Ülker, 2024 yılı ilk çeyrek finansallarını açıkladı](https://www.bloomberght.com/ulker-2024-yili-ilk-ceyrek-finansallarini-acikladi-2353853) |  |
| 38 | ZOREN | title | doğru | [Zorlu Enerji 2030 vadeli dolar tahvili rekor düşüşe ilerliyor](https://www.bloomberght.com/zorlu-enerji-2030-vadeli-dolar-tahvili-rekor-dususe-ilerliyor-3788254) |  |
| 39 | ALBRK | body | yanlış | [TCMB Başkanı Karahan, "İstanbul Dünya İslam Ekonomisi Zirvesi"nde konuştu](https://www.bloomberght.com/tcmb-baskani-karahan-istanbul-dunya-islam-ekonomisi-zirvesinde-konustu-3749598) | etkinlik adı: 'Türkiye Albaraka Zirveleri' |
| 40 | KORDS | title | doğru | [Kordsa'dan sermaye artırımı kararı](https://www.bloomberght.com/kordsa-dan-sermaye-artirimi-karari-3788684) |  |
| 41 | TAVHL | title | doğru | [Tav Havalimanları'ndan ikinci çeyrekte beklenti üstü net kâr](https://www.bloomberght.com/tav-havalimanlari-ndan-ikinci-ceyrekte-beklenti-ustu-net-kr-3784031) |  |
| 42 | GARAN | title | doğru | [Garanti BBVA/Akten: Enflasyondaki düşüş bizi pozitif etkiledi](https://www.bloomberght.com/garanti-bbvaakten-enflasyondaki-dusus-bizi-pozitif-etkiledi-3741887) |  |
| 43 | TSKB | code | zayıf | [Dof Robotik halka arz sonuçları açıklandı](https://www.bloomberght.com/dof-robotik-halka-arz-sonuclari-aciklandi-3756669) | halka arz konsorsiyum lideri |
| 44 | ISCTR | title | doğru | [İş Bankası Genel Müdürü Hakan Aran görevden ayrılıyor](https://www.bloomberght.com/is-bankasi-genel-muduru-hakan-aran-gorevden-ayriliyor-3784994) |  |
| 45 | TKFEN | body | yanlış | [Ercan Kumcu yaşamını yitirdi](https://www.bloomberght.com/ercan-kumcu-yasamini-yitirdi-3754521) | vefat haberi; kişinin eski unvanı |
| 46 | HALKB | title | doğru | [Halkbank'tan ABD'deki dava sürecine ilişkin açıklama](https://www.bloomberght.com/halkbank-tan-abd-deki-dava-surecine-iliskin-aciklama-3771384) |  |
| 47 | HALKB | title | doğru | [Halkbank’ta esnafa faiz artışı geçmişe uygulanmayacak](https://www.bloomberght.com/halkbankta-esnafa-faiz-artisi-gecmise-uygulanmayacak-2353386) |  |
| 48 | TURSG | title | doğru | [Türkiye Sigorta ve PTT AŞ güçlerini birleştirdi! / Son dakika ekonomi haberleri](https://www.bloomberght.com/turkiye-sigorta-ve-ptt-as-guclerini-birlestirdi-3742110) |  |
| 49 | ISCTR | body | doğru | [HSBC: Türk bankalarının değerlemelerinde yükseliş potansiyeli var](https://www.bloomberght.com/hsbc-turk-bankalarinin-degerlemelerinde-yukselis-potansiyeli-var-3790367) |  |
| 50 | VESTL | body | yanlış | [TÜFE ana harcama gruplarına göre yıllık değişim oranları](https://www.bloomberght.com/tufe-ana-harcama-gruplarina-gore-yillik-degisim-oranlari-3787265) | kazıma hatası: kenar kutusundaki başka haber başlığı |
| 51 | ISCTR | body | doğru | [Morgan Stanley, Türk bankalarında hedef düşürdü](https://www.bloomberght.com/morgan-turk-bankalarinda-hedef-dusurdu-2357038) |  |
| 52 | SISE | title | doğru | [Şişecam'dan yurt dışında şirket](https://www.bloomberght.com/sisecam-dan-yurt-disinda-sirket-2341425) |  |
| 53 | ARCLK | title | doğru | [Arçelik'in kurumsal markası Beko oluyor](https://www.bloomberght.com/arcelik-in-kurumsal-markasi-beko-oluyor-2350608) |  |
| 54 | TOASO | title | doğru | [Tofaş'tan Rekabet'in Stellantis kararına yönelik açıklama: Süreç devam ediyor](https://www.bloomberght.com/tofas-tan-rekabet-in-stellantis-kararina-yonelik-aciklama-surec-devam-ediyor-2363113) |  |
| 55 | HALKB | title | doğru | [Halkbank davası düşürüldü](https://www.bloomberght.com/halkbank-davasi-dusuruldu-3780340) |  |
| 56 | ASELS | title | doğru | [Aselsan Genel Müdürü Akyol: Bakiye siparişler 20 milyar doları aştı](https://www.bloomberght.com/aselsan-3770194) |  |
| 57 | PGSUS | title | doğru | [Pegasus yeni uçak siparişlerini değerlendiriyor](https://www.bloomberght.com/pegasus-yeni-ucak-siparislerini-degerlendiriyor-2343634) |  |
| 58 | OYAKC | title | doğru | [OYAK Çimento'dan 3. çeyrekte 3,4 milyar lira net kâr](https://www.bloomberght.com/oyak-cimento-dan-3-ceyrekte-3-4-milyar-lira-net-kr-3760699) |  |
| 59 | GARAN | title | doğru | [Garanti BBVA çift dilimli sendikasyon sağladı](https://www.bloomberght.com/garanti-bbva-cift-dilimli-sendikasyon-sagladi-2354457) |  |
| 60 | TSKB | code | doğru | [Galataport bankalarla yapılandırma anlaşması imzaladı](https://www.bloomberght.com/galataport-bankalarla-yapilandirma-anlasmasi-imzaladi-3737169) |  |
| 61 | KCHOL | title | doğru | [Koç Holding, 19,7 milyar TL ile beklentilerin üzerinde net kâr elde etti](https://www.bloomberght.com/koc-holding-19-7-milyar-tl-ile-beklentilerin-uzerinde-net-kr-elde-etti-3784802) |  |
| 62 | ASELS | title | doğru | [ASELSAN’dan 271,5 milyon dolarlık yeni savunma sözleşmesi](https://www.bloomberght.com/aselsandan-271-5-milyon-dolarlik-yeni-savunma-sozlesmesi-3779011) |  |
| 63 | YKBNK | title | yanlış | [Yapı Kredi Yatırım: Sis kalkıyor ama yol hâlâ dar](https://www.bloomberght.com/yapi-kredi-yatirim-sis-kalkiyor-ama-yol-hl-dar-3767688) | Yapı Kredi Yatırım'ın piyasa görünümü notu, bankayla ilgili değil |
| 64 | SISE | title | doğru | [Şişecam İtalya’daki yeni hat yatırımını tamamladı](https://www.bloomberght.com/sisecam-italyadaki-yeni-hat-yatirimini-tamamladi-3769573) |  |
| 65 | THYAO | title | doğru | [THY Elektronik Para ve Ödeme Hizmetleri A.Ş.'ye faaliyet izni](https://www.bloomberght.com/thy-elektronik-para-ve-odeme-hizmetleri-as-ye-faaliyet-izni-3745071) |  |
| 66 | TOASO | title | doğru | [Tofaş beklenti üzeri kâr açıkladı](https://www.bloomberght.com/tofas-beklenti-uzeri-kr-acikladi-3768739) |  |
| 67 | SAHOL | title | doğru | [Sabancı, ABD'li şirkete yatırım yaptı](https://www.bloomberght.com/sabanci-abd-li-sirkete-yatirim-yapti-2343555) |  |
| 68 | GARAN | title | doğru | [Garanti BBVA sendikasyon sağladı](https://www.bloomberght.com/garanti-bbva-sendikasyon-sagladi-3736069) |  |
| 69 | AKBNK | title | doğru | [Akbank Genel Müdürü Gür'den 2026 öngörüleri / Son dakika ekonomi haberleri](https://www.bloomberght.com/akbank-genel-muduru-gur-den-2026-ongoruleri-3762035) |  |
| 70 | TURSG | body | yanlış | [“Yabancı risk almakta iştahlı davranmıyor”](https://www.bloomberght.com/yabanci-risk-almakta-istahli-davranmiyor-2345598) | 'Türkiye sigorta piyasası' = sektör, şirket değil |
| 71 | THYAO | title | doğru | [THY'den ek sefer ve tavan fiyat açıklaması / Son dakika ekonomi haberleri](https://www.bloomberght.com/thy-yurt-ici-bilet-tavan-fiyatini-1750-lira-olarak-belirledi-3746992) |  |
| 72 | AKBNK | body | doğru | [HSBC'den Türk bankacılık sektörü analizi](https://www.bloomberght.com/hsbc-den-turk-banka-hissesi-yorumu-2353789) |  |
| 73 | THYAO | body | doğru | [Havayolu ulaşımına kar engeli / Son dakika ekonomi haberleri](https://www.bloomberght.com/havayolu-ulasimina-kar-engeli-3765963) |  |
| 74 | FROTO | body | doğru | [Koç Holding CEO'su Çakıroğlu'ndan Davos'ta dijital dönüşüm mesajı](https://www.bloomberght.com/koc-holding-ceosu-cakiroglundan-davos-ta-dijital-donusum-mesaji-3767173) |  |
| 75 | ISCTR | title | doğru | [İş Bankası/Aran: Kredilerde enflasyon beklentileriyle uyumlu gidişat var](https://www.bloomberght.com/is-bankasiaran-kredilerde-enflasyon-beklentileriyle-uyumlu-gidisat-var-3755612) |  |
| 76 | ASELS | title | doğru | [Aselsan 44,4 milyon dolarlık ihracat sözleşmeleri imzaladı](https://www.bloomberght.com/aselsan-44-4-milyon-dolarlik-ihracat-sozlesmeleri-imzaladi-2360726) |  |
| 77 | ISCTR | title | doğru | [İş Bankası’ndan beklentilerin üzerinde kâr performansı](https://www.bloomberght.com/is-bankasi-ikinci-ceyrekte-17-4-milyar-tl-net-kr-acikladi-3754249) |  |
| 78 | KORDS | body | doğru | [Sabancı'dan 3. çeyrekte 679 milyon lira konsolide net kâr](https://www.bloomberght.com/sabanci-dan-3-ceyrekte-679-milyon-lira-konsolide-net-kr-3760800) |  |
| 79 | PGSUS | title | doğru | [Pegasus'un eurobondunda teklif süreci başladı](https://www.bloomberght.com/pegasus-un-eurobondunda-teklif-sureci-basladi-2359391) |  |
| 80 | TSKB | code | doğru | [Lopez: Orta Koridor’un ilk kısmının faaliyete geçmesi gerekiyor](https://www.bloomberght.com/lopez-orta-koridorun-ilk-kisminin-faaliyete-gecmesi-gerekiyor-2342566) |  |
| 81 | YKBNK | title | doğru | [Yapı Kredi dolar cinsi tahvil ihraç ediyor / Son dakika ekonomi haberleri](https://www.bloomberght.com/yapi-kredi-dolar-cinsi-tahvil-ihrac-ediyor-3742361) |  |
| 82 | ASELS | title | doğru | [Aselsan'dan beklenti üstü kâr](https://www.bloomberght.com/aselsan-dan-beklenti-ustu-kr-3760810) |  |
| 83 | ISCTR | title | doğru | [İş Bankası’ndan 500 milyon dolarlık Eurotahvil ihracı](https://www.bloomberght.com/is-bankasindan-500-milyon-dolarlik-eurotahvil-ihraci-3767869) |  |
| 84 | MGROS | title | doğru | [Migros/Tort: Ürünlerimizde trend olarak düşen enflasyonu görüyoruz](https://www.bloomberght.com/migros-tort-urunlerimizde-trend-olarak-dusen-enflasyonu-goruyoruz-2361381) |  |
| 85 | TURSG | title | doğru | [Türkiye Sigorta'dan ikinci çeyrekte 7 milyar TL net kâr](https://www.bloomberght.com/turkiye-sigorta-dan-ikinci-ceyrekte-7-milyar-tl-net-kr-3783279) |  |
| 86 | TUPRS | title | doğru | [Tüpraş'ın temettü tarihi netleşti](https://www.bloomberght.com/tupras-in-temettu-tarihi-netlesti-2350414) |  |
| 87 | YKBNK | title | doğru | [Yapı Kredi, deprem bölgesine 80 milyon dolarlık kaynak sağladı](https://www.bloomberght.com/yapi-kredi-deprem-bolgesine-80-milyon-dolarlik-kaynak-sagladi-2344098) |  |
| 88 | SAHOL | title | doğru | [Sabancı Holding, “Dünyanın En İyi 25 İşvereni” arasında](https://www.bloomberght.com/sabanci-holding-dunyanin-en-iyi-25-isvereni-arasinda-3789869) |  |
| 89 | YKBNK | title | doğru | [Yapı Kredi ve TEB'de yurt dışı borçlanma hazırlığı](https://www.bloomberght.com/yapi-kredi-ve-teb-de-yurt-disi-borclanma-hazirligi-2359474) |  |
| 90 | ISCTR | title | doğru | [İş Bankası ikinci çeyrek bilançosunu açıkladı](https://www.bloomberght.com/is-bankasi-ikinci-ceyrek-bilancosunu-acikladi-2357995) |  |
| 91 | AEFES | body | doğru | [Ocak'ta yabancının en çok alım-satım yaptığı hisseler](https://www.bloomberght.com/ocak-ta-yabancinin-en-cok-alim-satim-yaptigi-hisseler-3741447) |  |
| 92 | SASA | body | doğru | [Erdemoğlu Holding Sasa'da bu kez hisse alımı yaptı](https://www.bloomberght.com/erdemoglu-holding-sasa-da-bu-kez-hisse-alimi-yapti-2344298) |  |
| 93 | VESTL | title | doğru | [Vestel'den borç yapılandırma haberlerine ilişkin açıklama](https://www.bloomberght.com/vestel-den-borc-yapilandirma-haberlerine-iliskin-aciklama-3770125) |  |
| 94 | ISCTR | title | doğru | [İş Bankası yurt dışı tahvil ihracı için bankaları yetkilendirdi](https://www.bloomberght.com/is-bankasi-yurtdisi-tahvil-ihraci-icin-bankalari-yetkilendirdi-3757661) |  |
| 95 | OYAKC | body | doğru | [Rekabet Kurulu'ndan 17 çimento ve beton şirketine soruşturma](https://www.bloomberght.com/rekabet-kurulu-ndan-17-cimento-sirketine-sorusturma-2341665) |  |
| 96 | KCHOL | body | doğru | [Koç: Yapı Kredi için iddialarda belirtilen nitelikte bir görüşme söz konusu değil](https://www.bloomberght.com/koc-holding-yapi-kredi-de-iddialarda-belirtilen-nitelikte-bir-gorusme-soz-konusu-degil-3735937) |  |
| 97 | GARAN | body | doğru | [Morgan Stanley, Türk bankalarında hedef düşürdü](https://www.bloomberght.com/morgan-turk-bankalarinda-hedef-dusurdu-2357038) |  |
| 98 | HEKTS | body | doğru | [MSCI Türkiye endekslerinde değişiklik yapıldı](https://www.bloomberght.com/msci-turkiye-endekslerinde-degisiklik-yapildi-2347494) |  |
| 99 | AKBNK | title | doğru | [Akbank GM Gür, 2024’te de istikrar kazandırıcı adımların devamını bekliyor](https://www.bloomberght.com/akbank-gm-gur-2024te-de-istikrar-kazandirici-adimlarin-devamini-bekliyor-2344473) |  |
| 100 | CIMSA | body | doğru | [Sabancı 3. çeyrek sonuçlarını açıkladı, '5 yılda 20 milyar dolarlık Sabancı' hedefi koydu](https://www.bloomberght.com/sabanci-3-ceyrek-sonuclarini-acikladi-3733971) |  |

## Tur 2 örneği

| # | Hisse | Eşleşme | Sınıf | Başlık | Not |
|---|---|---|---|---|---|
| 1 | AKBNK | body | doğru | [JPMorgan dört Türk bankasını negatif izlemeye aldı](https://www.bloomberght.com/jpmorgan-dort-turk-bankasini-negatif-izlemeye-aldi-2346084) |  |
| 2 | ASELS | title | doğru | [Aselsan/Akyol: Yüksek teknolojiye odaklanacağız](https://www.bloomberght.com/aselsanakyol-yuksek-teknolojiye-odaklanacagiz-2343401) |  |
| 3 | AKBNK | title | doğru | [Akbank'tan 600 milyon dolarlık tahvil ihracı](https://www.bloomberght.com/akbank-tan-600-milyon-dolarlik-tahvil-ihraci-3769182) |  |
| 4 | YKBNK | body | zayıf | [SPK'dan kripto kararı](https://www.bloomberght.com/spk-dan-kripto-karari-3772994) | iştirak Yapı Kredi Blokzincir'in yeni platformu |
| 5 | ISCTR | title | doğru | [İş Bankası'nın net kârı tahminleri aştı / Son dakika ekonomi haberleri](https://www.bloomberght.com/is-bankasi-nin-kri-2024-un-son-ceyreginde-tahminleri-asti-3741489) |  |
| 6 | ISCTR | title | doğru | [İş Bankası'nda üst düzey atamalar](https://www.bloomberght.com/is-bankasi-nda-ust-duzey-atamalar-3771884) |  |
| 7 | HALKB | title | doğru | [Halkbank: ABD Mahkemesi’nin onayı ile dava tamamen sona erecek](https://www.bloomberght.com/halkbank-abd-mahkemesinin-onayi-ile-dava-tamamen-sona-erecek-3779618) |  |
| 8 | GARAN | title | doğru | [Garanti BBVA 2025 yılı son çeyrek bilançosunu açıkladı](https://www.bloomberght.com/garanti-bbva-2025-yili-son-ceyrek-bilancosunu-acikladi-3768292) |  |
| 9 | CIMSA | title | doğru | [Çimsa'ya yeşil enerji kredisi](https://www.bloomberght.com/cimsa-ya-yesil-enerji-kredisi-3733640) |  |
| 10 | PGSUS | title | doğru | [Pegasus, Orta Doğu ülkelerine uçuş iptallerini uzattı](https://www.bloomberght.com/pegasus-orta-dogu-ulkelerine-ucus-iptallerini-uzatti-3773626) |  |
| 11 | TSKB | code | zayıf | [Odine Solutions halka arz büyüklüğü 1,33 milyar TL oldu](https://www.bloomberght.com/odine-solutions-halka-arz-buyuklugu-1-33-milyar-tl-oldu-2349547) | halka arz aracısı olarak KAP açıklaması |
| 12 | AKBNK | title | doğru | [Akbank sendikasyon temin etti](https://www.bloomberght.com/akbank-sendikasyon-temin-etti-2351139) |  |
| 13 | YKBNK | title | doğru | [Yapı Kredi eurobond için yeniden ihraca çıktı](https://www.bloomberght.com/yapi-kredi-eurobond-icin-yeniden-ihraca-cikti-2342364) |  |
| 14 | ISCTR | body | zayıf | [Küresel ve ulusal dijital finans ekosistemi İstanbul’da buluştu](https://www.bloomberght.com/kuresel-ve-ulusal-dijital-finans-ekosistemi-istanbulda-bulustu-2351372) | fintek ödülü |
| 15 | AKBNK | body | doğru | [BofA'dan Türk bankacılık analizi](https://www.bloomberght.com/bofa-dan-turk-bankacilik-analizi-2362762) |  |
| 16 | VESTL | title | doğru | [Bloomberg: Vestel borç yapılandırmasında ileri aşamada](https://www.bloomberght.com/bloomberg-vestel-borc-yapilandirmasinda-ileri-asamada-3770088) |  |
| 17 | SASA | code | doğru | [Sasa'da 25 milyar dolarlık yatırım planı](https://www.bloomberght.com/sasa-da-25-milyar-dolarlik-yatirim-plani-3755681) |  |
| 18 | SELEC | code | doğru | [Üç hisseye kredili işlem yasağı](https://www.bloomberght.com/uc-hisseye-kredili-islem-yasagi-2359918) |  |
| 19 | TOASO | title | doğru | [Tofaş 3.çeyrekte 1,2 milyar TL net kâr açıkladı / Son dakika ekonomi haberleri](https://www.bloomberght.com/tofas-3ceyrekte-1-2-milyar-tl-net-kr-acikladi-3760698) |  |
| 20 | MGROS | title | doğru | [Migros'tan kâr payı dağıtım kararı](https://www.bloomberght.com/migros-tan-kr-payi-dagitim-karari-3746429) |  |
| 21 | ASELS | title | doğru | [Aselsan ile Havelsan arasında mutabakat zaptı](https://www.bloomberght.com/aselsan-ile-havelsan-arasinda-mutabakat-zapti-imzalandi-2346101) |  |
| 22 | AKBNK | title | doğru | [Akbank'tan 2024'ün son çeyreğinde 9,2 milyar TL net kâr](https://www.bloomberght.com/akbank-tan-2024-un-son-ceyreginde-9-2-milyar-tl-net-kr-3740493) |  |
| 23 | ASELS | title | doğru | [Aselsan, radar üretim kapasitesini üç katına çıkaracak](https://www.bloomberght.com/aselsan-radar-uretim-kapasitesini-uc-katina-cikaracak-3739230) |  |
| 24 | OYAKC | title | doğru | [Oyak Çimento'dan bedelsiz sermaye artırımı](https://www.bloomberght.com/oyak-cimento-dan-bedelsiz-sermaye-artirimi-2353277) |  |
| 25 | GARAN | body | doğru | [BBVA, Garanti'nin satışı haberlerini yalanladı](https://www.bloomberght.com/bbva-garanti-nin-satisi-haberlerini-yalanladi-2352890) |  |
| 26 | CIMSA | title | doğru | [Çimsa ABD'deki yatırımını devreye aldı](https://www.bloomberght.com/cimsa-abd-deki-yatirim-devreye-aldi-3759143) |  |
| 27 | HALKB | title | doğru | [Halkbank’ın üç aylık net kârı beklentiyi aştı](https://www.bloomberght.com/halkbankin-uc-aylik-net-kri-beklentiyi-asti-3777194) |  |
| 28 | ASELS | title | doğru | [Aselsan ile Roketsan arasında sözleşme değişikliği](https://www.bloomberght.com/aselsan-ile-roketsan-arasinda-sozlesme-degisikligi-2356060) |  |
| 29 | YKBNK | body | doğru | [Borsada yeni zirve](https://www.bloomberght.com/borsada-yeni-zirve-2350764) |  |
| 30 | TTKOM | title | doğru | [Türk Telekom: Bizim altyapımız Türkiye'nin altyapısıdır](https://www.bloomberght.com/turk-telekom-bizim-altyapimizturkiye-nin-altyapisidir-3755903) |  |
| 31 | ENKAI | body | doğru | [Enka işti̇raki, bir ABD şirketiyle 527,5 milyon dolarlık sözleşme imzaladı](https://www.bloomberght.com/enka-istiraki-bir-abd-sirketiyle-527-5-milyon-dolarlik-sozlesme-imzaladi-3749186) |  |
| 32 | TSKB | title | doğru | [TSKB'den 300 milyon dolarlık tahvil ihracı](https://www.bloomberght.com/tskb-den-300-milyon-dolarlik-tahvil-ihraci-3781476) |  |
| 33 | SAHOL | title | doğru | [Sabancı/Cenk Alper: İşlerimizi doğayla uyumlu hale getirmeliyiz](https://www.bloomberght.com/sabancicenk-alper-islerimizi-dogayla-uyumlu-hale-getirmeliyiz-3740012) |  |
| 34 | THYAO | title | doğru | [THY’den Boeing siparişi](https://www.bloomberght.com/thyden-boeing-siparisi-3758005) |  |
| 35 | TATGD | title | doğru | [Tat Gıda'nın satışı tamamlandı](https://www.bloomberght.com/tat-gida-nin-satisi-tamamlandi-2347880) |  |
| 36 | ENJSA | title | doğru | [Enerjisa Enerji üst yönetiminde görev değişimi](https://www.bloomberght.com/enerjisa-enerji-ust-yonetiminde-gorev-degisimi-3789787) |  |
| 37 | YKBNK | body | doğru | [Koç Holding'ten 2025 yılı 4. çeyrekte 7 milyar TL net kâr](https://www.bloomberght.com/koc-holding-ten-2025-yili-4-ceyrekte-7-milyar-tl-net-kr-3768891) |  |
| 38 | CCOLA | body | zayıf | [Anadolu Efes’te üst düzey iki atama](https://www.bloomberght.com/anadolu-efeste-ust-duzey-iki-atama-2348568) | atanan yöneticinin önceki görevi Coca-Cola İçecek |
| 39 | GARAN | title | doğru | [Garanti Bankası'nın net kârı beklentileri aştı](https://www.bloomberght.com/garanti-bankasi-nin-net-kri-beklentileri-asti-3776188) |  |
| 40 | KCHOL | body | yanlış | [27 Türk dünya milyarderler liginde](https://www.bloomberght.com/27-turk-dunya-milyarderler-liginde-2350487) | milyarderler listesi; 'Koç Holding YK üyesi' unvanı |
| 41 | HALKB | title | doğru | [Halkbank 88. yılını kutluyor](https://www.bloomberght.com/halkbank-88-yilini-kutluyor-3778390) |  |
| 42 | BIMAS | body | doğru | [Borsada şirketlerin geri alımları sürüyor](https://www.bloomberght.com/borsada-sirketlerin-geri-alimlari-suruyor-3744818) |  |
| 43 | PGSUS | title | doğru | [Pegasus'ta bilet fiyatlamada yapay zeka kullanımı](https://www.bloomberght.com/pegasus-ta-bilet-fiyatlamada-yapay-zeka-kullanimi-3737638) |  |
| 44 | HALKB | title | doğru | [Halkbank’ın esnaf ve sanatkârlara yönelik kredilerin faiz indiriminde değişiklik](https://www.bloomberght.com/halkbankin-esnaf-ve-sanatkrlara-yonelik-kredilerin-faiz-indiriminde-degisiklik-3786539) |  |
| 45 | BIMAS | body | doğru | [HSBC Türk perakende hisselerinde hedeflerini güncelledi](https://www.bloomberght.com/hsbc-turk-perakende-hisselerinde-hedeflerini-guncelledi-3767057) |  |
| 46 | SISE | title | doğru | [Şişecam Yönetim Kurulu Başkanı Adnan Bali oldu](https://www.bloomberght.com/sisecam-yonetim-kurulu-baskani-adnan-bali-oldu-2355508) |  |
| 47 | ISCTR | title | doğru | [İş Bankası "Türkiye'nin en değerli banka markası" seçildi](https://www.bloomberght.com/is-bankasi-turkiye-nin-en-degerli-banka-markasi-secildi-2348976) |  |
| 48 | ISCTR | title | doğru | [İş Bankası’ndan kurucu intifa senedi açıklaması / Son dakika ekonomi haberleri](https://www.bloomberght.com/is-bankasindan-kurucu-intifa-senedi-aciklamasi-3745156) |  |
| 49 | BIMAS | body | doğru | [Türkiye'de 120 milyar doları aşan gıda perakendeciliğinin röntgeni](https://www.bloomberght.com/turkiye-de-120-milyar-dolari-asan-gida-perakendeciliginin-rontgeni-3782601) |  |
| 50 | GLYHO | title | doğru | [Global Yatırım Holding hisse geri alım programı başlattı](https://www.bloomberght.com/global-yatirim-holding-hisse-geri-alim-programi-baslatti-3744720) |  |
| 51 | VAKBN | title | doğru | [Vakıfbank, yurt dışından yeni kaynak temin etti](https://www.bloomberght.com/vakifbank-yurt-disindan-yeni-kaynak-temin-etti-2348892) |  |
| 52 | TUPRS | body | doğru | [Borsada jeopolitik baskı](https://www.bloomberght.com/borsada-jeopolitik-baski-2340198) |  |
| 53 | TSKB | code | yanlış | [Hedef Portföy’e yeni Genel Müdür atandı / Son dakika ekonomi haberleri](https://www.bloomberght.com/hedef-portfoye-yeni-genel-mudur-atandi-3762159) | biyografi: eski TSKB CFO'su |
| 54 | SISE | title | doğru | [Şişecam'ın kum hazırlama tesisinin çelik işlerini Karçel üstlendi](https://www.bloomberght.com/sisecam-in-kum-hazirlama-tesisinin-celik-islerini-karcel-ustlendi-2357212) |  |
| 55 | SAHOL | title | doğru | [Sabancı Holding CEO'su Zaimler: Yurt dışındaki fırsatlara bakacağız](https://www.bloomberght.com/sabanci-holding-ceo-su-zaimler-yurt-disindaki-firsatlara-bakacagiz-3766888) |  |
| 56 | KRDMD | body | doğru | [MSCI Türkiye endeksinde güncelleme](https://www.bloomberght.com/msci-turkiye-endeksinde-guncelleme-3760912) |  |
| 57 | ARCLK | body | doğru | [Ford Otosan Koçfinans'ı bünyesine kattı](https://www.bloomberght.com/ford-otosan-kocfinans-i-bunyesine-katti-3781665) |  |
| 58 | KCHOL | title | doğru | [Koç Holding Kemer Medical Center’ın yüzde 80’ini satın aldı](https://www.bloomberght.com/koc-holding-kemer-medical-centerin-yuzde-80ini-satin-aldi-2350157) |  |
| 59 | ARCLK | title | doğru | [Arçelik ve Yapı Kredi Leasing'ten güneş enerjisi işbirliği](https://www.bloomberght.com/arcelik-ve-yapi-kredi-leasing-ten-gunes-enerjisi-isbirligi-3735679) |  |
| 60 | YKBNK | title | doğru | [Yapı Kredi'den 500 milyon dolarlık tahvil ihracı](https://www.bloomberght.com/yapi-kredi-den-500-milyon-dolarlik-tahvil-ihraci-3763165) |  |
| 61 | ASELS | title | doğru | [Türk Telekom ve Aselsan'dan stratejik işbirliği](https://www.bloomberght.com/turk-telekom-ve-aselsan-dan-stratejik-isbirligi-3778008) |  |
| 62 | MGROS | title | doğru | [Migros’ta satışlar arttı, kârlılık düştü](https://www.bloomberght.com/migrosta-satislar-artti-krlilik-dustu-2353531) |  |
| 63 | THYAO | title | doğru | [Fitch'ten THY yorumu: Latin Amerika ağ erişimi güçlenecek](https://www.bloomberght.com/fitch-ten-thy-yorumu-latin-amerika-ag-erisimi-guclenecek-3756738) |  |
| 64 | KRDMD | title | doğru | [Borsada gong Kardemir Çelik için çaldı](https://www.bloomberght.com/borsada-gong-kardemir-celik-icin-caldi-3784389) |  |
| 65 | SOKM | title | doğru | [Şok Market, İstegelsin'i satın aldı](https://www.bloomberght.com/sok-market-istegelsin-i-satin-aldi-2351120) |  |
| 66 | MIATK | body | doğru | [Borsa İstanbul’da pazar kriterleri değişti, endeksler yeniden şekillendi](https://www.bloomberght.com/borsa-istanbulda-pazar-kriterleri-degisti-endeksler-yeniden-sekillendi-3789023) |  |
| 67 | GARAN | title | doğru | [Garanti BBVA'dan kripto yasası yorumu](https://www.bloomberght.com/garanti-bbva-dan-kripto-yasasi-yorumu-2355532) |  |
| 68 | MPARK | title | doğru | [MLP Sağlık'ta yabancı ortak hisselerini sattı](https://www.bloomberght.com/mlp-saglik-ta-yabanci-ortak-hisselerini-satti-3754007) |  |
| 69 | GARAN | title | doğru | [Garanti BBVA'da temettü teklifi açıklandı](https://www.bloomberght.com/garanti-bbva-da-temettu-teklifi-aciklandi-2349123) |  |
| 70 | ASELS | title | doğru | [Aselsan, 42 milyon dolarlık ihracat sözleşmesi imzaladı](https://www.bloomberght.com/aselsan-42-milyon-dolarlik-ihracat-sozlesmesi-imzaladi-3738159) |  |
| 71 | ASELS | title | doğru | [Aselsan'dan 26,2 milyon dolarlık sözleşme](https://www.bloomberght.com/aselsan-dan-26-2-milyon-dolarlik-sozlesme-2361558) |  |
| 72 | TTRAK | title | doğru | [Türk Traktör'den satın alma](https://www.bloomberght.com/turk-traktor-den-satin-alma-3733380) |  |
| 73 | ISCTR | title | doğru | [İş Bankası Kıbrıs’ta 70. yılında](https://www.bloomberght.com/is-bankasi-kibrista-70-yilinda-3746923) |  |
| 74 | ULKER | body | zayıf | [Yıldız Holding'de yeni dönem](https://www.bloomberght.com/yildiz-holding-de-yeni-donem-3747296) | ana ortak Yıldız Holding'te başkan değişimi, KAP'a Ülker Bisküvi üzerinden |
| 75 | ISCTR | body | zayıf | ["KOBİ’lerin likiditeleri yoğun bir şekilde bozuldu"](https://www.bloomberght.com/kobilerin-likiditeleri-yogun-bir-sekilde-bozuldu-3762102) | İş Bankası GMY'nin KOBİ likiditesi yorumu |
| 76 | THYAO | title | doğru | [THY'nin New York uçuşlarına olumsuz hava engeli](https://www.bloomberght.com/thy-nin-new-york-ucuslarina-olumsuz-hava-engeli-3769832) |  |
| 77 | HALKB | body | zayıf | [Kredi için 99,4 milyon liralık BES fonu teminat gösterildi](https://www.bloomberght.com/kredi-icin-99-4-milyon-liralik-bes-fonu-teminat-gosterildi-2360597) | BES teminatlı kredi talep eden bankalar arasında |
| 78 | MIATK | title | doğru | [MİA Teknoloji'den ABD yatırımı değerlendirmesi](https://www.bloomberght.com/mia-teknoloji-abd-de-hisse-satisiyla-yurt-disi-yatirimi-yapacak-2341194) |  |
| 79 | ENJSA | title | doğru | [Enerjisa'dan rekor tahvil ihracı](https://www.bloomberght.com/enerjisa-dan-rekor-tahvil-ihraci-3741437) |  |
| 80 | KCHOL | body | doğru | [Ömer Koç: 2025'in riskleri tedarik zinciri ve korumacı tedbirler olacak](https://www.bloomberght.com/omer-koc-2025-in-riskleri-tedarik-zinciri-ve-korumaci-tedbirler-olacak-3735896) |  |
| 81 | EKGYO | title | doğru | [Emlak Konut'tan indirim kampanyası](https://www.bloomberght.com/emlak-konut-tan-indirim-kampanyasi-2353832) |  |
| 82 | ASELS | title | doğru | [ASELSAN'dan 54 milyon dolarlık sözleşme](https://www.bloomberght.com/aselsan-dan-54-milyon-dolarlik-sozlesme-3742956) |  |
| 83 | TAVHL | body | doğru | [SPK’dan 3 şirketin halka arz başvurusuna onay](https://www.bloomberght.com/spkdan-3-sirketin-halka-arz-basvurusunu-onay-2342544) |  |
| 84 | KCHOL | title | doğru | [Koç Holding'ten kredi notu açıklaması](https://www.bloomberght.com/koc-holding-ten-kredi-notu-aciklamasi-2357314) |  |
| 85 | BIMAS | body | doğru | [JPMorgan 3 yıl sonra bir Türk şirketini 'Top 10' listesine ekledi](https://www.bloomberght.com/jpmorgan-3-yil-sonra-bir-turk-sirketini-top-10-listesine-ekledi-2339575) |  |
| 86 | CIMSA | body | doğru | [Sabancı CEO'su Alper: 'Yatırım yap' diyen bir bilançomuz var / Son dakika ekonomi haberleri](https://www.bloomberght.com/sabanci-ceo-su-alper-yatirim-yap-diyen-bir-bilancomuz-var-3743586) |  |
| 87 | KRDMD | title | doğru | [Kardemir'de yeni yönetim belirlendi](https://www.bloomberght.com/kardemir-de-yeni-yonetim-belirlendi-2340589) |  |
| 88 | EKGYO | title | doğru | [Emlak Konut ile Suudi Arabistan'ın ulusal konut şirket arasında anlaşma](https://www.bloomberght.com/emlak-konut-ile-suudi-arabistan-in-ulusal-konut-sirket-arasinda-anlasma-3736047) |  |
| 89 | THYAO | body | doğru | [Erdoğan ve Trump Beyaz Saray’da görüşecek](https://www.bloomberght.com/erdogan-ve-trump-beyaz-sarayda-gorusecek-3757633) |  |
| 90 | VAKBN | body | yanlış | [“İrade Bizim, Zafer Bizim” sergisi ziyaretçileriyle buluştu](https://www.bloomberght.com/irade-bizim-zafer-bizim-sergisi-ziyaretcileriyle-bulustu-3783247) | mekân adı: 'VakıfBank Sanat Galerisi' |
| 91 | TUPRS | title | doğru | [Tüpraş’tan sermaye tavanı artırımı başvurusu](https://www.bloomberght.com/tuprastan-sermaye-tavani-artirimi-basvurusu-3740248) |  |
| 92 | ENJSA | title | doğru | [EBRD'den Enerjisa'ya 100 milyon dolarlık destek](https://www.bloomberght.com/ebrd-denenerjisa-ya-100-milyon-dolarlik-destek-2346585) |  |
| 93 | TAVHL | body | doğru | [Rekabet Kurulu bazı devralma işlemlerini onayladı](https://www.bloomberght.com/rekabet-kurulu-bazi-devralma-islemlerini-onayladi-2353829) |  |
| 94 | ISCTR | title | doğru | [İş Bankası'ndan dijital tahvil ihracı](https://www.bloomberght.com/is-bankasi-ndan-dijital-tahvil-ihraci-3751700) |  |
| 95 | KRDMD | title | doğru | [Goldman Sachs Kardemir'de yine pay artırdı](https://www.bloomberght.com/goldman-sachs-kardemir-de-yine-pay-artirdi-3791051) |  |
| 96 | VAKBN | title | doğru | [Vakıfbank’tan 2. çeyrekte 7,2 milyar lira net kâr](https://www.bloomberght.com/vakifbanktan-2-ceyrekte-7-2-milyar-lira-net-kr-2358115) |  |
| 97 | AEFES | title | doğru | [Anadolu Efes'ten tarımsal ekonomiye 1.3 milyar TL'lik katkı](https://www.bloomberght.com/anadolu-efes-ten-tarimsal-ekonomiye-13-milyar-tl-lik-katki-2357172) |  |
| 98 | ALBRK | body | doğru | [Rekabet'ten bankalara soruşturma](https://www.bloomberght.com/rekabet-ten-bankalara-sorusturma-3769945) |  |
| 99 | KRDMD | title | doğru | [Kardemir ray ihalesi kazandı](https://www.bloomberght.com/kardemir-ray-ihalesi-kazandi-2362210) |  |
| 100 | TUPRS | body | doğru | [7 başlıkta geçen hafta](https://www.bloomberght.com/7-baslikta-gecen-hafta-3760578) |  |
