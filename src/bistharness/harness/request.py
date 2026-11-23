"""Analysis requests: a structured form of the user's question, and a deterministic Turkish question parser.

The UI and the golden suite pass structured requests; free text is parsed by keyword rules (no LLM), so the scenario
choice is reproducible. An advice/target-price request always becomes SAFETY_ADVICE_REQUEST, whatever else it asks.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bistharness.core.config import Universe
from bistharness.core.enums import Scenario

ADVICE_RE = re.compile(  # \b: "normal mi" must not match "al mi"
    r"\b(alay[ıi]m m[ıi]|almal[ıi] m[ıi]y[ıi]m|alal[ıi]m m[ıi]|al m[ıi]|sat m[ıi]|satay[ıi]m m[ıi]|satmal[ıi] m[ıi]y[ıi]m|"
    r"hedef fiyat|kesin (y[üu]kselir|d[üu]şer|kazand[ıi]r)|ne zaman al|tavsiye( eder| verir)? ?m(i|isin)|"
    # forward-looking gain / timing / sizing requests (not historical: "kazandırmış" / "kazandıran" do not match)
    r"kazand[ıi]r[ıi]r|kazan[ıi]r m[ıi]y[ıi]m|ne kazan[ıi]r[ıi]m|yat[ıi]rsam|al[ıi]m f[ıi]rsat[ıi]|"
    r"al[ıi]n[ıi]r m[ıi]|sat[ıi]l[ıi]r m[ıi]|stop (seviye|nere)|tavan olur|taban olur|"
    r"\b(buy|sell)\b|target price)",
    re.IGNORECASE,
)
KEYWORDS: dict[Scenario, re.Pattern[str]] = {
    Scenario.S2_WEEKDAY_PATTERN: re.compile(
        r"haftan[ıi]n g[üu]n|pazartesi|sal[ıi]|çarşamba|perşembe|cuma|\bpzt\b|\bper\b|\bcum\b|takvim|g[üu]n [öo]r[üu]nt",
        re.IGNORECASE,
    ),
    Scenario.S3_TECHNICAL_REVERSAL: re.compile(
        r"bollinger|\brsi\b|supertrend|ichimoku|kama|teknik d[öo]n[üu]ş|dip|destek|diren[çc]|d[öo]n[üu]ş olay",
        re.IGNORECASE,
    ),
    Scenario.S4_FUNDAMENTAL_REACTION: re.compile(
        r"bilan[çc]o|fav[öo]k|ebitda|[çc]eyrek|temel analiz|\bkap\b|net bor[çc]|finansal rapor|a[çc][ıi]klama sonras",
        re.IGNORECASE,
    ),
    Scenario.S1_SECTOR_CATCH_UP: re.compile(
        r"sekt[öo]r|geride kal|catch|yeti[şs]|lider|laggard|akran|kapanma", re.IGNORECASE
    ),
}
TICKER_RE = re.compile(r"\b[A-ZÇĞİÖŞÜ]{4,6}\b")


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str
    scenario: Scenario
    tickers: list[str] = Field(min_length=1)
    as_of_date: date
    start: date = date(2024, 1, 1)
    end: date | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    advice_requested: bool = False

    @property
    def primary(self) -> str:
        return self.tickers[0]


class QuestionParseError(ValueError):
    pass


def parse_question(question: str, *, as_of: date, universe: Universe, start: date | None = None) -> AnalysisRequest:
    known = set(universe.all_stock_tickers())
    tickers = list(dict.fromkeys(t for t in TICKER_RE.findall(question) if t in known))
    if not tickers:
        raise QuestionParseError("soruda evrendeki bir hisse kodu bulunamadı (örn. ASELS, TUPRS)")
    advice = bool(ADVICE_RE.search(question))
    if advice:
        scenario = Scenario.SAFETY_ADVICE_REQUEST
    else:
        scores = {s: len(rx.findall(question)) for s, rx in KEYWORDS.items()}
        hits = [s for s, n in sorted(scores.items(), key=lambda kv: -kv[1]) if n > 0]  # stable: ties keep dict order
        if not hits:
            raise QuestionParseError(
                "senaryo anlaşılamadı: sektör / haftanın günü / teknik dönüş / bilanço sözcüklerinden "
                "birini kullanın ya da formdan senaryo seçin"
            )
        scenario = hits[0]
    return AnalysisRequest(
        question=question,
        scenario=scenario,
        tickers=tickers,
        as_of_date=as_of,
        start=start or date(2024, 1, 1),
        advice_requested=advice,
    )
