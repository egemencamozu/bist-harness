"""Varied Turkish questions for the fine-tuning dataset (deterministic for a seed; no LLM).

Diversity axes: many templates per scenario, ticker codes vs company names, lower case / missing Turkish characters,
greetings, multi-ticker and sector questions, advice traps, out-of-scope requests. Every generated question carries the
structured target (scenario, tickers, params, advice flag, in_scope) used as the intent label.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import yaml

from bistharness.core.config import Universe, project_root
from bistharness.core.enums import Scenario

SECTOR_TR = {
    "Bankacilik": "bankacılık",
    "Sigorta_Araci_Kurum": "sigorta ve aracı kurum",
    "Holding_Yatirim": "holding",
    "Bilisim_Yazilim": "bilişim",
    "Demir_Celik_Boru": "demir çelik",
    "Insaat_Yapi_Malzemeleri": "inşaat ve çimento",
    "GYO": "gayrimenkul yatırım ortaklığı",
    "Otomotiv_YanSanayi": "otomotiv",
    "Dayanikli_Tuketim": "dayanıklı tüketim",
    "Enerji": "enerji",
    "Petrokimya_Endustri": "petrokimya",
    "Tarim_Gubre": "gübre",
    "Gida_Icecek": "gıda ve içecek",
    "Perakende": "perakende",
    "Havacilik_Lojistik": "havacılık",
    "Savunma_Makine": "savunma",
    "Telekomunikasyon": "telekom",
    "Saglik_Ilac": "sağlık",
}

S1 = [
    "{g} arasında son {h} işlem gününde sektör medyanının gerisinde kalan hangisi?",
    "{sector} sektöründe son {h} günde geride kalan hisse var mı, geçmişte bu tür geride kalanlar toparlanmış mı?",
    "{g} için lider ve geride kalanları sıralar mısın? Geride kalanlar sonradan yetişmiş mi?",
    "{t} akranlarına göre geride mi kaldı? Catch-up ihtimali tarihsel olarak nasıl?",
    "Son {h} günde {sector} hisseleri içinde en zayıf kalan hangisi ve bu zayıflık yapısal mı?",
    "{g} grubunda geride kalma girişlerinin 5/10/20 günlük kapanma oranı ve yanlış pozitifleri nedir?",
    "{t} sektörünün gerisinde mi, POTENTIAL_CATCH_UP_CANDIDATE olur mu?",
    "{sector} sektöründe kim önde kim geride, son {h} işlem günü?",
]
S2 = {
    "MON_TUE_WED_DOWN__THU_FRI": [
        "{t}'de Pazartesi-Salı-Çarşamba düşüşünden sonra Perşembe-Cuma yükseliş oluyor mu?",
        "{t} ilk üç gün düşünce haftanın son iki günü toparlıyor mu? Örneklem dışında da geçerli mi?",
        "{t} için pzt-sal-çar düşüş, per-cum yükseliş örüntüsünü işlem maliyetiyle test eder misin?",
    ],
    "MON_DOWN__FRI": [
        "{t} pazartesi düşerse cuma günü yükseliyor mu?",
        "{t} haftaya düşüşle başladığında cuma getirisi nasıl oluyor?",
    ],
    "MON_TO_THU_UP__FRI": [
        "{t} pazartesiden perşembeye her gün yükselirse cuma da devam ediyor mu?",
        "{t}'de dört gün üst üste yükselişten sonra cuma günü ne oluyor?",
    ],
    "THREE_DOWN_DAYS": [
        "{t} üç gün üst üste düştükten sonra ertesi gün tepki veriyor mu?",
        "{t}'de art arda üç düşüş gününden sonraki getiriler nasıl?",
    ],
    "LARGE_DOWN_DAY": [
        "{t} sert düştüğü günün ertesinde toparlanıyor mu?",
        "{t}'de büyük düşüş günlerinden sonra ortalama getiri ne?",
    ],
}
S3 = [
    "{t}'de alt Bollinger bandına değince 5 gün sonra yükseliş oranı nedir?",
    "{t} için teknik dönüş sinyallerinin geçmiş başarısı nasıl?",
    "{t}'de RSI dibi ve hacim artışıyla gelen alt bant dokunuşları daha mı başarılı?",
    "{t} Supertrend düşüş yönündeyken ve bulutun altındayken alt banda değmesi işe yarıyor mu?",
    "{t} için Bollinger, RSI, Supertrend ve Ichimoku olaylarını karşılaştırır mısın?",
    "{t}'de destek seviyelerine yaklaşınca tepki geliyor mu?",
    "{t}'de şu an aktif bir teknik dönüş olayı var mı ve geçmişte bu olay işe yaramış mı?",
    "{t} teknik olarak dipten dönüyor mu? Tamamlanmamış son pencereleri hariç tut.",
]
S4 = [
    "{t}'nin son bilançosunda FAVÖK marjı ve Net Borç/FAVÖK nasıl değişti?",
    "{t} bilanço açıklamalarından sonra XU100'e göre nasıl performans gösterdi?",
    "{t} son çeyrekte kârlılığını artırdı mı, açıklama sonrası fiyat tepkisi ne oldu?",
    "{t} için KAP açıklama tarihleriyle çeyreklik temel değişimi ve 1/5/20 günlük anormal getiriyi çıkarır mısın?",
    "{t}'de temel iyileşme var mı, geçmişte iyileşen raporlardan sonra hisse ne yapmış?",
    "{t}'nin son finansal raporu ne zaman açıklandı ve 20 günlük penceresi tamam mı?",
]
SAFETY = [
    "{t} kesin yükselir mi? Hemen alayım mı?",
    "{t} için hedef fiyat verir misin?",
    "{t}'ye şimdi girsem kazanır mıyım?",
    "{t}'yi satmalı mıyım yoksa tutmalı mıyım?",
    "Dolar yükseliyor, {t} ihracatçı olduğu için kesin yükselir, yarın alayım mı? Hedef fiyat ver.",
    "{t} için stop seviyesi ve hedef fiyat nedir?",
    "{t} yarın kaç TL olur, alsam mı?",
    "Hocam {t} garanti yükselir mi, ne tavsiye edersin?",
]
OUT_OF_SCOPE = [
    ("Bitcoin bu hafta yükselir mi?", True, "kripto varlıklar analiz evreninde değil"),
    ("Apple hissesi için teknik analiz yapar mısın?", False, "yabancı hisseler analiz evreninde değil"),
    ("Altın alsam mı?", True, "emtia yatırım tavsiyesi verilmez ve emtia evrende değil"),
    ("Dolar yarın kaç TL olur?", False, "gelecek fiyat tahmini yapılmaz"),
    ("BIST 100 yıl sonunda kaç puan olur?", False, "gelecek seviye tahmini yapılmaz"),
    ("Bana bir şiir yazar mısın?", False, "finansal analiz dışı istek"),
    ("Tesla mı Ford Otosan mı daha iyi?", False, "yabancı hisseler analiz evreninde değil"),
    ("Hangi hisse kesin kazandırır?", True, "yatırım tavsiyesi verilmez"),
]
GREETINGS = ("", "", "", "Hocam, ", "Merhaba, ", "Bir sorum var: ", "Rica etsem ")
TR_PLAIN = str.maketrans("ıİğĞüÜşŞöÖçÇ", "iIgGuUsSoOcC")


@dataclass
class Question:
    text: str
    in_scope: bool
    scenario: Scenario | None
    tickers: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    advice: bool = False
    reason: str = ""


def company_names() -> dict[str, list[str]]:
    with (project_root() / "config" / "news.yaml").open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return {t: [n.title() for n in spec.get("names", [])] for t, spec in raw["tickers"].items()}


def _style(text: str, rng: random.Random) -> str:
    r = rng.random()
    if r < 0.15:
        text = text.lower()
    elif r < 0.25:
        text = text.translate(TR_PLAIN)
    return rng.choice(GREETINGS) + text


def _name(t: str, names: dict[str, list[str]], rng: random.Random) -> str:
    if t in names and names[t] and rng.random() < 0.3:
        return rng.choice(names[t])
    return t.lower() if rng.random() < 0.08 else t


def _join(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " ve " + items[-1] if len(items) > 1 else items[0]


def make_question(
    scenario: Scenario,
    tickers: list[str],
    rng: random.Random,
    names: dict[str, list[str]],
    universe: Universe,
    params: dict[str, Any] | None = None,
) -> Question:
    params = dict(params or {})
    t = tickers[0]
    shown = [_name(x, names, rng) for x in tickers]
    if scenario is Scenario.S1_SECTOR_CATCH_UP:
        h = params.get("horizon", 20)
        group = universe.instrument(t).peer_group or ""
        tmpl = rng.choice(S1)
        text = tmpl.format(g=_join(shown), t=shown[0], h=h, sector=SECTOR_TR.get(group, "aynı sektör"))
    elif scenario is Scenario.S2_WEEKDAY_PATTERN:
        tmpl = rng.choice(S2[params["pattern"]])
        text = tmpl.format(t=shown[0])
    elif scenario is Scenario.S3_TECHNICAL_REVERSAL:
        text = rng.choice(S3).format(t=shown[0])
    elif scenario is Scenario.S4_FUNDAMENTAL_REACTION:
        text = rng.choice(S4).format(t=shown[0])
    else:
        text = rng.choice(SAFETY).format(t=shown[0])
    return Question(
        _style(text, rng), True, scenario, list(tickers), params, scenario is Scenario.SAFETY_ADVICE_REQUEST
    )


def out_of_scope(rng: random.Random) -> Question:
    text, advice, reason = rng.choice(OUT_OF_SCOPE)
    return Question(_style(text, rng), False, None, [], {}, advice, reason)
