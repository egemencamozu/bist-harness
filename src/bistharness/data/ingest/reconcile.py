"""Pure functions that turn two price sources into one validated, adjustable price series.

Design (final, 2026-11-21 — see CLAUDE.md §11):

* PRIMARY = FinTreX price-scraper wherever it publishes its adjusted layer (`adj_close`, `adj_factor`): printed
  OHLCV from verified 5-minute bars and bonus/rights/split factors on ex-dates taken from ekofin and verified against
  prices (e.g. CCOLA 1:11 bonus on 2024-08-13, HEKTS 2024-09-18, TUKAS 2025-02-04, TATGD 2024-12-26).
* SECONDARY = yfinance, used for:
  - dividends: the price-scraper deliberately does not adjust dividends; yfinance `Adj Close / Close` is a pure
    dividend factor (split adjustments cancel out in the ratio);
  - tickers the price-scraper marks as unsupported (no adjusted layer, e.g. BIMAS, MAVI), XU100, TRALT;
  - days after the price-scraper snapshot ends and days it is missing.
* Known yfinance defects this design avoids: truncated bars (2023-01-05 THYAO close 141.8 vs real 135.2,
  2022-12-16 AKBNK volume 73M vs 280M); bonus issues recorded on the right date but with history adjusted only a few
  days back (CCOLA: split 11 on 2024-08-13, prices adjusted only from 2024-08-01 -> fake -91 % day; TUKAS 2025-02-03);
  bonus issues with no split record at all (HEKTS, TATGD, KATMR, ZOREN, RYSAS). Disagreements -> SOURCE_DISAGREEMENT.
* A primary daily return that is implausible (|r| > BIST price band) falls back to the secondary for that day.
* The trading calendar comes from the price-scraper majority (yfinance emits phantom rows, e.g. 2023-02-08).
* Output per day: printed (raw) OHLCV and cum_factor with  adjusted_t = raw_t * cum_factor_t  (cum_factor_last = 1).
  cum_factor = split/bonus component (piecewise constant) x dividend component, so it never carries vendor noise.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from bistharness.core.enums import Severity, WarningCode
from bistharness.data.ingest.yahoo import valid_rows

OHLC = ["open", "high", "low", "close"]
ACTION_COLS = ["ex_date", "ratio", "kind", "detail", "source"]


@dataclass(frozen=True)
class Flag:
    ticker: str
    date: date | None
    code: WarningCode
    severity: Severity
    detail: str = ""

    def as_row(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "date": self.date.isoformat() if self.date else None,
            "code": self.code.value,
            "severity": self.severity.value,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------- calendar
def build_trading_calendar(
    bar_dates: Mapping[str, pd.DatetimeIndex],
    majority: float,
    extension_dates: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """A day is a trading day if at least `majority` of the tickers whose history spans it have a bar.

    `extension_dates` (e.g. XU100 days from yfinance) are appended only after the last majority day.
    Returns columns: date (Timestamp), source, n_tickers.
    """
    counts: Counter[pd.Timestamp] = Counter()
    spans: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for idx in bar_dates.values():
        if len(idx) == 0:
            continue
        counts.update(idx)
        spans.append((idx.min(), idx.max()))
    rows: list[dict[str, object]] = []
    for d in sorted(counts):
        n_active = sum(1 for lo, hi in spans if lo <= d <= hi)
        if n_active and counts[d] >= majority * n_active:
            rows.append({"date": d, "source": "price_scraper_majority", "n_tickers": counts[d]})
    cal = pd.DataFrame(rows, columns=["date", "source", "n_tickers"])
    if extension_dates is not None and len(extension_dates):
        last = cal["date"].max() if len(cal) else pd.Timestamp.min
        ext = sorted(d for d in extension_dates if d > last)
        if ext:
            cal = pd.concat(
                [cal, pd.DataFrame({"date": ext, "source": "xu100_yfinance", "n_tickers": None})],
                ignore_index=True,
            )
    return cal.sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- yfinance helpers
def yf_unadjust_splits(yf: pd.DataFrame) -> pd.DataFrame:
    """yfinance 'Close' is retroactively split-adjusted. Undo it with the 'Stock Splits' column so that
    raw_* columns hold the prices actually printed on each day (as far as yfinance's split records are right)."""
    splits = yf["Stock Splits"].fillna(0.0)
    ratio = splits.where(splits > 0, 1.0)
    after = ratio[::-1].cumprod()[::-1].shift(-1).fillna(1.0)  # product of split ratios strictly AFTER each date
    out = yf.copy()
    for c in ["Open", "High", "Low", "Close"]:
        out[f"raw_{c.lower()}"] = yf[c] * after
    out["raw_volume"] = yf["Volume"] / after
    return out


def _yf_detail(ex_date: pd.Timestamp, yf_actions: pd.DataFrame, column: str) -> str:
    lo, hi = ex_date - pd.Timedelta(days=4), ex_date + pd.Timedelta(days=4)
    win = yf_actions.loc[(yf_actions.index >= lo) & (yf_actions.index <= hi), column].fillna(0)
    hit = win[win > 0]
    return f"yfinance {column.lower()} {float(hit.iloc[0]):g}" if len(hit) else f"no yfinance {column.lower()} record"


def _pct(g: float | None) -> str:
    return "n/a" if g is None else f"{g - 1:+.4f}"


# --------------------------------------------------------------------------- per-ticker reconciliation
@dataclass
class ReconcileResult:
    prices: pd.DataFrame  # index date; open high low close volume (printed) + cum_factor, price_source, factor_source
    actions: pd.DataFrame  # ACTION_COLS
    flags: list[Flag]


def _empty_result(flags: list[Flag]) -> ReconcileResult:
    prices = pd.DataFrame(
        columns=[*OHLC, "volume", "cum_factor", "price_source", "factor_source"],
        index=pd.DatetimeIndex([], name="date"),
    )
    return ReconcileResult(prices, pd.DataFrame(columns=ACTION_COLS), flags)


@dataclass(frozen=True)
class _Inputs:
    """Both sources of one ticker, cleaned and aligned to the trading calendar."""

    ticker: str
    ps: pd.DataFrame | None  # price-scraper bars on trading days with close > 0 (None = no usable bar)
    ps_ok: frozenset[pd.Timestamp]  # days whose price-scraper adjusted layer is usable
    yv: pd.DataFrame  # valid yfinance bars on trading days, with printed raw_* columns
    yadj: pd.Series  # yfinance Adj Close
    divf: pd.Series  # dividend-only factor on `span`
    span: pd.DatetimeIndex  # trading days between the first and last bar of either source
    yf_actions: pd.DataFrame  # yfinance Dividends / Stock Splits (for action details)

    @property
    def ps_index(self) -> pd.DatetimeIndex:
        return self.ps.index if self.ps is not None else pd.DatetimeIndex([])

    @property
    def primary_ps(self) -> bool:
        return bool(self.ps_ok)

    @property
    def primary(self) -> str:
        return "price_scraper" if self.primary_ps else "yfinance"

    def ps_frame(self) -> pd.DataFrame:
        if self.ps is None:
            raise ValueError(f"{self.ticker}: no price-scraper bars")
        return self.ps


@dataclass(frozen=True)
class _Chain:
    """Result of chaining daily gross returns: adjusted level, chosen source and both sources' returns per day."""

    adj: pd.Series  # adjusted close level (arbitrary base), index = days
    source: dict[pd.Timestamp, str]
    g_primary: dict[pd.Timestamp, float | None]
    g_secondary: dict[pd.Timestamp, float | None]

    @property
    def days(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.adj.index)


def reconcile_ticker(
    ticker: str,
    ps: pd.DataFrame | None,
    yf: pd.DataFrame | None,
    calendar: pd.DatetimeIndex,
    *,
    band: float,
    min_log_change: float,
    source_disagreement: float,
) -> ReconcileResult:
    """Reconcile one ticker. Steps: clean inputs -> chain daily returns -> cross-check -> factor -> OHLCV -> actions."""
    flags: list[Flag] = []
    ps_clean = _clean_price_scraper(ticker, ps, calendar, flags)
    yv = _clean_yfinance(ticker, yf, calendar, flags) if yf is not None and not yf.empty else None
    if yf is None or yv is None:
        return _ps_only(ticker, ps_clean, flags) if ps_clean is not None else _empty_result(flags)

    inp = _build_inputs(ticker, ps_clean, yv, yf, calendar)
    _flag_source_roles(inp, flags)
    chain = _chain_daily_returns(inp, band=band, flags=flags)
    _flag_disagreements(inp, chain, threshold=source_disagreement, flags=flags)
    split_part, anchors, printed_anchor = _split_component(inp, chain)
    factor = split_part * inp.divf.loc[chain.days]
    prices = _printed_ohlcv(inp, chain, factor, anchors, printed_anchor)
    actions = _corporate_actions(inp, split_part, chain.days, min_log_change=min_log_change)
    return ReconcileResult(prices=prices, actions=actions, flags=flags)


# --------------------------------------------------------------------------- step 0: inputs
def _clean_price_scraper(
    ticker: str, ps: pd.DataFrame | None, calendar: pd.DatetimeIndex, flags: list[Flag]
) -> pd.DataFrame | None:
    if ps is None or ps.empty:
        return None
    for d in ps.index.difference(calendar):
        flags.append(
            Flag(
                ticker,
                d.date(),
                WarningCode.PHANTOM_ROW_DROPPED,
                Severity.INFO,
                "price_scraper bar on a non-trading day",
            )
        )
    clean = ps[ps.index.isin(calendar) & (ps["close"] > 0)]
    return None if clean.empty else clean


def _clean_yfinance(
    ticker: str, yf: pd.DataFrame, calendar: pd.DatetimeIndex, flags: list[Flag]
) -> pd.DataFrame | None:
    yfu = yf_unadjust_splits(yf)
    ok = valid_rows(yf)
    for d in yf.index[ok & ~yf.index.isin(calendar)]:
        flags.append(
            Flag(ticker, d.date(), WarningCode.PHANTOM_ROW_DROPPED, Severity.INFO, "yfinance bar on a non-trading day")
        )
    yv = yfu[ok & yf.index.isin(calendar)]
    return None if yv.empty else yv


def _build_inputs(
    ticker: str, ps: pd.DataFrame | None, yv: pd.DataFrame, yf: pd.DataFrame, calendar: pd.DatetimeIndex
) -> _Inputs:
    ps_ok: frozenset[pd.Timestamp] = frozenset()
    ps_index = pd.DatetimeIndex([])
    if ps is not None:
        ps_ok = frozenset(ps.index[ps["ps_has_adj"].astype(bool) & (ps["ps_adj_close"] > 0)])
        ps_index = ps.index
    first = min(yv.index.min(), ps_index.min()) if len(ps_index) else yv.index.min()
    last = max(yv.index.max(), ps_index.max()) if len(ps_index) else yv.index.max()
    span = calendar[(calendar >= first) & (calendar <= last)]
    yadj = yv["Adj Close"].astype(float)
    # dividend-only factor (split adjustments, right or wrong, cancel in Adj Close / Close)
    divf = (yadj / yv["Close"].astype(float)).reindex(span).ffill().bfill()
    return _Inputs(
        ticker=ticker,
        ps=ps,
        ps_ok=ps_ok,
        yv=yv,
        yadj=yadj,
        divf=divf,
        span=span,
        yf_actions=yf[["Dividends", "Stock Splits"]],
    )


def _flag_source_roles(inp: _Inputs, flags: list[Flag]) -> None:
    if inp.ps is not None and not inp.primary_ps:
        flags.append(
            Flag(
                inp.ticker,
                None,
                WarningCode.ADJUSTMENT_FROM_SECONDARY,
                Severity.INFO,
                "price_scraper has no adjusted layer for this ticker (unsupported); yfinance is primary",
            )
        )
    if inp.ps is None:
        flags.append(
            Flag(inp.ticker, None, WarningCode.SINGLE_SOURCE, Severity.INFO, "yfinance only; no cross-check source")
        )


# --------------------------------------------------------------------------- step 1: chain daily gross returns
def _chain_daily_returns(inp: _Inputs, *, band: float, flags: list[Flag]) -> _Chain:
    """Pick, day by day, the first plausible gross return in source priority order and chain it.

    Each source is chained from ITS OWN last good day, so a one-day gap or glitch never shifts later levels.
    """
    ps_index, yv, yadj, divf = inp.ps_index, inp.yv, inp.yadj, inp.divf
    ps_last = ps_index.max() if len(ps_index) else None
    adj: dict[pd.Timestamp, float] = {}
    source: dict[pd.Timestamp, str] = {}
    g_primary: dict[pd.Timestamp, float | None] = {}
    g_secondary: dict[pd.Timestamp, float | None] = {}
    prev: pd.Timestamp | None = None
    last_ps: pd.Timestamp | None = None  # last day whose level came from the price-scraper adjusted layer
    last_yf: pd.Timestamp | None = None  # last processed day with a valid yfinance bar
    for d in inp.span:
        in_yf, in_ps = d in yv.index, d in ps_index
        if prev is None:
            if in_yf or in_ps:
                adj[d] = 1.0
                source[d] = "price_scraper" if d in inp.ps_ok else ("yfinance" if in_yf else "price_scraper_raw")
                prev = d
                last_ps = d if d in inp.ps_ok else None
                last_yf = d if in_yf else None
            continue
        base = adj[prev]
        g_ps = None
        if d in inp.ps_ok and last_ps is not None:
            ps = inp.ps_frame()
            level = adj[last_ps] * float(ps.at[d, "ps_adj_close"] / ps.at[last_ps, "ps_adj_close"])
            g_ps = level * float(divf[d] / divf[last_ps]) / base
        g_yf = float(adj[last_yf] * yadj[d] / yadj[last_yf] / base) if in_yf and last_yf is not None else None
        g_raw = None
        if g_ps is None and in_ps and prev in ps_index:
            ps = inp.ps_frame()
            g_raw = float(ps.at[d, "close"] / ps.at[prev, "close"]) * float(divf[d] / divf[prev])

        if inp.primary_ps:
            order = [(g_ps, "price_scraper"), (g_yf, "yfinance"), (g_raw, "price_scraper_raw")]
        else:  # price-scraper unsupported for this ticker: its raw layer is not trusted except as last resort
            order = [(g_yf, "yfinance"), (g_raw, "price_scraper_raw")]
        chosen = next(((g, s) for g, s in order if g is not None and abs(g - 1) <= band), None)
        if chosen is None:  # nothing plausible: keep the best available, quality checks will flag the jump
            chosen = next(((g, s) for g, s in order if g is not None), None)
        if chosen is None:
            flags.append(
                Flag(inp.ticker, d.date(), WarningCode.MISSING_DAY, Severity.SOFT, "no usable bar in either source")
            )
            continue
        g, s = chosen
        adj[d] = base * g
        source[d] = s
        if s == "price_scraper":
            last_ps = d
        if in_yf:
            last_yf = d
        g_primary[d] = g_ps if inp.primary_ps else g_yf
        g_secondary[d] = g_yf if inp.primary_ps else (g_ps if g_ps is not None else g_raw)
        if not s.startswith(inp.primary):
            after_end = inp.primary_ps and ps_last is not None and d > ps_last
            flags.append(
                Flag(
                    inp.ticker,
                    d.date(),
                    WarningCode.FILLED_FROM_SECONDARY,
                    Severity.INFO if after_end else Severity.SOFT,
                    f"{s} used ({'after price_scraper snapshot end' if after_end else 'primary missing or implausible'})",
                )
            )
        prev = d
    days = pd.DatetimeIndex(sorted(adj))
    return _Chain(
        adj=pd.Series([adj[d] for d in days], index=days),
        source=source,
        g_primary=g_primary,
        g_secondary=g_secondary,
    )


# --------------------------------------------------------------------------- step 2: cross-source validation
def _flag_disagreements(inp: _Inputs, chain: _Chain, *, threshold: float, flags: list[Flag]) -> None:
    for d in chain.days:
        a, b = chain.g_primary.get(d), chain.g_secondary.get(d)
        if a is not None and b is not None and abs(a - b) > threshold:
            used_primary = chain.source[d] == inp.primary
            flags.append(
                Flag(
                    inp.ticker,
                    d.date(),
                    WarningCode.SOURCE_DISAGREEMENT,
                    Severity.INFO if used_primary else Severity.SOFT,
                    f"daily return primary {_pct(a)} vs secondary {_pct(b)}; used {chain.source[d]}",
                )
            )


# --------------------------------------------------------------------------- step 3: split/bonus component
def _split_component(inp: _Inputs, chain: _Chain) -> tuple[pd.Series, list[pd.Timestamp], pd.Series]:
    """Split/bonus factor component (piecewise constant), measured on days whose level came from the primary.

    Returns (split_part on all days, anchor days, printed close on the anchor days).
    """
    days = chain.days
    anchors = [d for d in days if chain.source[d] == inp.primary]
    if inp.primary_ps:
        printed_anchor = inp.ps_frame().loc[anchors, "close"].astype(float)
    else:
        printed_anchor = inp.yv.loc[anchors, "raw_close"].astype(float)
    split_part = (chain.adj.loc[anchors] / printed_anchor / inp.divf.loc[anchors]).reindex(days).ffill().bfill()
    return split_part, anchors, printed_anchor


# --------------------------------------------------------------------------- step 4: printed OHLCV
def _printed_ohlcv(
    inp: _Inputs, chain: _Chain, factor: pd.Series, anchors: list[pd.Timestamp], printed_anchor: pd.Series
) -> pd.DataFrame:
    """Printed close = primary print on anchor days, else adjusted level / factor. OHL keep the chosen bar's shape.
    Volume: price-scraper volume when its close matches the printed close, else turnover-preserving yfinance volume."""
    days, ps_index, yv = chain.days, inp.ps_index, inp.yv
    out = pd.DataFrame(index=days, columns=[*OHLC, "volume"], dtype=float)
    out["close"] = chain.adj / factor
    if len(anchors):
        out.loc[anchors, "close"] = printed_anchor.to_numpy(dtype=float)
    for d in days:
        close = float(out.at[d, "close"])
        bar = None
        if chain.source[d].startswith("price_scraper") and d in ps_index:
            r = inp.ps_frame().loc[d]
            bar = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        elif d in yv.index:
            y = yv.loc[d]
            bar = (float(y["raw_open"]), float(y["raw_high"]), float(y["raw_low"]), float(y["raw_close"]))
        if bar is not None and bar[3] > 0:
            out.at[d, "open"], out.at[d, "high"], out.at[d, "low"] = (close * v / bar[3] for v in bar[:3])
        else:
            out.at[d, "open"] = out.at[d, "high"] = out.at[d, "low"] = close
        vol = 0.0
        if d in ps_index:
            ps = inp.ps_frame()
            if abs(float(ps.at[d, "close"]) / close - 1) < 0.02:
                vol = float(ps.at[d, "volume"])  # same share scale as the printed price
        if not vol > 0 and d in yv.index:
            vol = float(yv.at[d, "raw_volume"]) * float(yv.at[d, "raw_close"]) / close  # turnover preserving
        out.at[d, "volume"] = vol

    out["cum_factor"] = factor / factor.iloc[-1]
    out["price_source"] = pd.Series(chain.source).reindex(days)
    out["factor_source"] = "price_scraper_adj+yfinance_dividends" if inp.primary_ps else "yfinance_adj"
    out.index.name = "date"
    return out


# --------------------------------------------------------------------------- step 5: corporate actions
def _corporate_actions(
    inp: _Inputs, split_part: pd.Series, days: pd.DatetimeIndex, *, min_log_change: float
) -> pd.DataFrame:
    """Corporate actions = changes of the factor components (split/bonus from the primary, dividends from yfinance)."""
    rows: list[dict[str, object]] = []
    d_split = np.log(split_part.astype(float)).diff()
    for d, v in d_split[d_split.abs() > min_log_change].items():
        ratio = float(np.exp(v))
        kind = "split_or_bonus" if ratio >= 1.25 else ("reverse_split" if ratio < 1 else "rights_or_other")
        rows.append(
            {
                "ex_date": d,
                "ratio": ratio,
                "kind": kind,
                "detail": _yf_detail(d, inp.yf_actions, "Stock Splits"),
                "source": inp.primary,
            }
        )
    d_div = np.log(inp.divf.loc[days].astype(float)).diff()
    for d, v in d_div[d_div.abs() > min_log_change].items():
        rows.append(
            {
                "ex_date": d,
                "ratio": float(np.exp(v)),
                "kind": "dividend",
                "detail": _yf_detail(d, inp.yf_actions, "Dividends"),
                "source": "yfinance",
            }
        )
    return pd.DataFrame(rows, columns=ACTION_COLS).sort_values("ex_date").reset_index(drop=True)


def _ps_only(ticker: str, ps: pd.DataFrame | None, flags: list[Flag]) -> ReconcileResult:
    """Fallback without yfinance: price-scraper bonus/rights adjustment only, dividends unadjusted."""
    assert ps is not None
    base = ps[ps["close"] > 0]
    out = base[[*OHLC, "volume"]].astype(float).copy()
    adj = (base["ps_adj_close"] / base["close"]).where(base["ps_has_adj"].astype(bool))
    out["cum_factor"] = adj.ffill().bfill().fillna(1.0)
    out["cum_factor"] = out["cum_factor"] / out["cum_factor"].iloc[-1]
    out["price_source"] = "price_scraper"
    out["factor_source"] = "price_scraper_adj"
    out.index.name = "date"
    flags.append(
        Flag(
            ticker, None, WarningCode.DIVIDENDS_NOT_ADJUSTED, Severity.SOFT, "no yfinance data; dividends not adjusted"
        )
    )
    return ReconcileResult(out, pd.DataFrame(columns=ACTION_COLS), flags)
