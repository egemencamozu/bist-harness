"""Helpers shared by the tools: input resolution, point-in-time loading and evidence construction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from bistharness.analytics import series
from bistharness.analytics.forward_returns import StudyParams
from bistharness.core.calendar import TradingCalendar
from bistharness.core.config import Instrument
from bistharness.core.dates import to_date
from bistharness.core.enums import Severity, WarningCode
from bistharness.core.errors import ConfigError, DataNotFoundError
from bistharness.core.schemas import EvidenceCandidate, WarningItem
from bistharness.tools.base import ToolContext, ToolInputError


def instrument(ctx: ToolContext, ticker: str, *, kind: str | None = None) -> Instrument:
    try:
        inst = ctx.universe.instrument(ticker.upper())
    except ConfigError as exc:
        raise ToolInputError(f"unknown ticker {ticker!r}") from exc
    if kind is not None and inst.kind != kind:
        raise ToolInputError(f"{ticker} is a {inst.kind}, not a {kind}")
    return inst


@dataclass(frozen=True)
class Window:
    start: date
    end: date  # <= as_of
    as_of: date
    clamped: bool


def window(ctx: ToolContext, start: date | None, end: date | None, as_of: date) -> Window:
    s = start or ctx.settings.date("analysis_start")
    e = end or as_of
    clamped = e > as_of
    e = min(e, as_of)
    if s > e:
        raise ToolInputError(f"start {s} is after the effective end {e}")
    return Window(s, e, as_of, clamped)


def study_params(ctx: ToolContext, horizons: Sequence[int] | None = None, threshold: float = 0.0) -> StudyParams:
    hz = tuple(sorted(set(horizons))) if horizons else ctx.settings.horizons
    if any(h < 1 for h in hz):
        raise ToolInputError("horizons must be >= 1")
    return StudyParams(
        horizons=hz,
        success_threshold=threshold,
        small_sample=int(ctx.settings.threshold("small_sample")),
        insufficient_sample=int(ctx.settings.threshold("insufficient_sample")),
    )


def calendar(ctx: ToolContext, as_of: date) -> TradingCalendar:
    return ctx.repo.trading_calendar(as_of=as_of)


def load_prices(
    ctx: ToolContext, tickers: Sequence[str], as_of: date, *, optional: Sequence[str] = ()
) -> tuple[pd.DataFrame, list[WarningItem]]:
    """Adjusted (as_of-anchored) prices from the warm-up start; indicators never depend on the window start.

    `tickers` must have data (DataNotFoundError otherwise); `optional` ones (peers, basket members) without any price
    up to as_of are left out with a PRICE_MISSING info warning."""
    start = ctx.settings.date("warmup_start")
    req = list(dict.fromkeys(tickers))
    opt = [t for t in dict.fromkeys(optional) if t not in req]
    try:
        pf = ctx.repo.prices(req + opt, start, as_of=as_of)
        return pf.data, list(pf.warnings)
    except DataNotFoundError:
        if not opt:
            raise
    ok, warnings = [], []
    for t in opt:
        try:
            ctx.repo.prices(t, start, as_of=as_of)
            ok.append(t)
        except DataNotFoundError:
            warnings.append(
                WarningItem(
                    code=WarningCode.PRICE_MISSING,
                    severity=Severity.INFO,
                    ticker=t,
                    detail=f"{t}: no price data up to {as_of}; left out of the basket",
                )
            )
    pf = ctx.repo.prices(req + ok, start, as_of=as_of)
    return pf.data, list(pf.warnings) + warnings


def available(prices: pd.DataFrame, tickers: Sequence[str]) -> list[str]:
    have = set(prices["ticker"])
    return [t for t in tickers if t in have]


def ohlcv(prices: pd.DataFrame, ticker: str) -> pd.DataFrame:
    return series.ohlcv(prices, ticker)


def raw_close(prices: pd.DataFrame, ticker: str) -> pd.Series:
    df = prices[prices["ticker"] == ticker]
    return pd.Series(df["raw_close"].to_numpy(dtype=float), index=pd.DatetimeIndex(df["date"]))


def peers_of(ctx: ToolContext, ticker: str) -> list[str]:
    return [t for t in ctx.universe.peers(ticker) if t != ticker]


def ts(d: date) -> pd.Timestamp:
    return pd.Timestamp(to_date(d))


def direction(
    x: float | None, *, up: str = "yükseldi", down: str = "düştü", flat: str = "değişmedi", eps: float = 1e-12
) -> str:
    """Direction word computed from the number itself, so an explanation copies it instead of inferring it."""
    if x is None:
        return "-"
    return up if x > eps else down if x < -eps else flat


def compare(
    a: float | None, b: float | None, *, higher: str = "daha yüksek", lower: str = "daha düşük", same: str = "aynı"
) -> str:
    if a is None or b is None:
        return "-"
    return direction(a - b, up=higher, down=lower, flat=same)


def correlation_words(r: float | None) -> str:
    if r is None:
        return "-"
    a = abs(r)
    strength = "çok zayıf" if a < 0.1 else "zayıf" if a < 0.3 else "orta" if a < 0.5 else "güçlü"
    return f"{'negatif' if r < 0 else 'pozitif'}, {strength}"


def evidence(
    key: str,
    template: str,
    display: dict[str, str],
    *,
    values: dict[str, Any] | None = None,
    pointer: str = "",
    kind: str = "fact",
    primary: bool = False,
) -> EvidenceCandidate:
    """claim_tr = template.format(**display): every number in the claim is one of the display strings."""
    return EvidenceCandidate(
        key=key,
        claim_tr=template.format(**display),
        values=values or {},
        display=display,
        json_pointer=pointer,
        kind=kind,
        primary=primary,
    )
