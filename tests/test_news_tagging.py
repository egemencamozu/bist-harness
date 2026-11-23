"""Deterministic news tagging and the conservative knowledge-time rule (synthetic articles)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bistharness.core.config import project_root
from bistharness.data.ingest import news

TAGGER = news.Tagger.load(project_root() / "config" / "news.yaml")


def test_turkish_lowercase_and_timezone() -> None:
    assert news.tr_lower("İSTANBUL BIST 100") == "istanbul bıst 100"
    assert news.to_istanbul("2024-08-01T03:43:51+00:00") == "2024-08-01 06:43:51"
    assert news.to_istanbul("2024-08-01T09:00:00+03:00") == "2024-08-01 09:00:00"


@pytest.mark.parametrize(
    ("title", "body", "expected"),
    [
        ("Türk Hava Yolları yolcu sayısını açıkladı", "", ["THYAO"]),
        ("Havacılıkta yeni dönem", "Şirketin hissesi THYAO güne yükselişle başladı.", ["THYAO"]),
        ("Savunma sanayinde ihracat", "Aselsan bir sözleşme imzaladı.", []),  # one body mention is not enough
        ("Savunma sanayinde ihracat", "Aselsan bir sözleşme imzaladı. Aselsan payları yükseldi.", ["ASELS"]),
        ("BİM yeni mağazalar açıyor", "", ["BIMAS"]),
        ("bim bam bom", "", []),  # exact tokens are case-sensitive
        ("Gökyüzü mavi, piyasalar sakin", "Mavi bir gün. Mavi renk.", []),  # 'mavi' = blue, not MAVI
        ("Mavi Giyim satışlarını artırdı", "", ["MAVI"]),
        (
            "Ekonomi ve siyaset gündemi - 1 Ağustos 2024",
            "Aselsan ... Aselsan ... THYAO ... Tüpraş ... Tüpraş",
            [],
        ),  # round-up page: body mentions ignored
        ("Ford Otosan ve Tofaş satış rakamları", "", ["FROTO", "TOASO"]),
        ("Borsada gün sonu", "THYAO, ASELS, TUPRS, EREGL ve AKBNK öne çıktı.", []),  # recap: > 4 body-only tickers
        ("Piyasa özeti: 13 Mart 2024", "THYAO yükseldi.", []),  # recap title
        # exclude lists (2026-11-23 precision audit): associations / unlisted siblings are not the listed company
        ("Türkiye Sigorta Birliği Başkanı açıklama yaptı", "", []),
        ("Türkiye Sigorta'dan yeni ürün", "", ["TURSG"]),
        ("Enerjisa Üretim yatırımlarını sürdürüyor", "", []),
        ("Enerjisa dağıtım bölgelerinde yatırım", "", ["ENJSA"]),
        ("Vestel Beyaz Eşya ihracatını artırdı", "", ["VESBE"]),
        ("Vestel'den eurobond yapılandırması", "", ["VESTL"]),
        ("Alarko GYO yeni proje", "", ["ALGYO"]),
        ("Akbank Yönetim Kurulu Başkanı Suzan Sabancı konuştu", "", ["AKBNK"]),
        ("Sabancı Holding'ten net kâr", "", ["SAHOL"]),
        # code: false — DEVA is the party; the company only by its name
        ("DEVA Partisi Genel Başkanı açıklama yaptı", "", []),
        ("Deva Holding ihracat anlaşması imzaladı", "", ["DEVA"]),
        # ambiguous everyday words are not aliases
        ("Efes antik kentine ziyaretçi akını", "", []),
        ("Anadolu Efes'ten lokavt kararı", "", ["AEFES"]),
        ("TAV'dan beklentilere paralel kâr", "", ["TAVHL"]),
        ("Demirin tavında dövülmesi", "", []),
        ("Erkut Çelebi sanayicilerle buluştu", "", []),
        ("Çelebi Hava Servisi satın alma yaptı", "", ["CLEBI"]),
        # second audit round (2026-11-23): market / research desk / event names
        ("Deprem teminatı", "Türkiye sigorta piyasasının teminatı arttı. Türkiye sigorta sektörü büyüdü.", []),
        ("Yapı Kredi Yatırım: Sis kalkıyor ama yol hâlâ dar", "", []),
        ("Yapı Kredi'den tahvil ihracı", "", ["YKBNK"]),
        ("Karahan konuştu", "Türkiye Albaraka Zirveleri kapsamında... Albaraka zirvesinde...", []),
    ],
)
def test_ticker_matching(title: str, body: str, expected: list[str]) -> None:
    assert TAGGER.tickers(title, body) == expected


def test_topics_follow_priority_and_word_boundaries() -> None:
    assert TAGGER.topics_of("TCMB politika faizini sabit tuttu", "")[0] == "rates"
    t = TAGGER.topics_of("Tüpraş bilançosunu açıkladı", "Dolar/TL yükselirken şirketin net kârı arttı.")
    assert t[:1] == ["earnings"] and "fx" in t
    assert "fx" not in TAGGER.topics_of("Yönetim kurulu toplandı", "Kurul kararı açıklandı.")
    assert TAGGER.topics_of("Fed'in kararı bekleniyor", "") == ["fed"]
    assert TAGGER.topics_of("BIST 100 güne yükselişle başladı", "") == ["equity_market"]


def test_knowledge_time_is_the_latest_version_time(tmp_path: Path) -> None:
    payload = {
        "messages": [
            {
                "published_at": "2023-10-01T07:13:22+00:00",
                "articles": {
                    "https://example.org/a": {
                        "title": "Başlık",
                        "text": "Metin",
                        "page_published_at": "2023-09-30T19:22:17+00:00",  # first published
                        "page_modified_at": "2023-10-01T07:13:22+00:00",  # archived text is this version
                    }
                },
            },
            {"published_at": "2023-10-02T07:00:00+00:00", "articles": {}},  # message without an article
        ]
    }
    f = tmp_path / "bloomberg_ht_6_2023-10.json"
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (a,) = list(news.iter_articles([f]))
    assert a.first_published_at == "2023-09-30 22:22:17"
    assert a.knowledge_at == "2023-10-01 10:13:22"
    df = news.tag_articles([a], TAGGER)
    assert df.iloc[0]["published_at"] == "2023-10-01 10:13:22"
    assert df.iloc[0]["event_id"] == news.event_id("https://example.org/a")


def test_every_universe_ticker_is_tagged() -> None:
    from bistharness.core.config import load_universe

    uni = load_universe()
    stocks = {t for g in uni.peer_groups.values() for t in g} | set(uni.tickers("course_30"))
    assert stocks == set(TAGGER.universe) and len(TAGGER.universe) == 96


def test_headline_of_another_article_copied_into_a_body_is_not_a_mention() -> None:
    def art(url: str, title: str, text: str) -> news.Article:
        return news.Article(url, title, text, "2026-01-02 10:00:00", "2026-01-02 10:00:00")

    vestel = art(
        "https://x/v", "Vestel'den eurobond sahiplerine iki seçenekli yapılandırma teklifi", "Vestel açıkladı."
    )
    box = "Diğer haberler: Vestel'den eurobond sahiplerine iki seçenekli yapılandırma teklifi | Petrol düştü"
    cpi = art("https://x/c", "TÜFE ana harcama gruplarına göre yıllık değişim", f"Enflasyon açıklandı. {box} {box}")
    real = art("https://x/r", "Zorlu Grubu borç yapılandırması", "Vestel grubu kredileri... Vestel ve tekstil grubu.")
    df = news.tag_articles([vestel, cpi, real], TAGGER).set_index("url")
    assert json.loads(df.loc["https://x/v", "tickers"]) == ["VESTL"]
    assert json.loads(df.loc["https://x/c", "tickers"]) == []  # only the copied related-news headline
    assert json.loads(df.loc["https://x/r", "tickers"]) == ["VESTL"]  # genuine body mentions still count
    # without the archive-wide title index the same body is (wrongly) tagged: the rule is what fixes it
    assert TAGGER.tickers(cpi.title, cpi.text) == ["VESTL"]
