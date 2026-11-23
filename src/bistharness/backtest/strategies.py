"""Strategy variants A-E (spec §29) as layered, point-in-time daily masks (pure).

A_TECH              entry = any of the technical entry events (long only) [+ volume above its 20-day mean]
B_TECH_SECTOR       A and the stock trails its peers (20-day lag score <= sector_max_lag) in a strong sector
C_TECH_SECTOR_FUND  B and the latest KAP report KNOWN that day shows same-report YoY top-line growth > threshold
                    and higher YTD net income than the prior-year YTD
D_FULL_STRUCTURED   C and no macro stress known that day: USD/TRY change over 21 trading days <= 5% and no TCMB
                    rate hike released in the previous 30 calendar days
E_FULL_CONTEXTUAL   D and no ticker-tagged news with an event-risk topic (regulation, geopolitics) published in the
                    last 2 trading days (news is context only: no numbers from headlines are used)

Every mask value on day d uses only information with knowledge time <= d 23:59:59 (prices: close of d; KAP:
disclosure_datetime; macro: release_datetime; news: conservative published_at); the engine executes at d+1 open.
The preset (REVERSAL_PRESET_V1) was fixed before any backtest result was looked at; changing it after seeing results
is data mining and must be reported as such.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bistharness.analytics import fundamentals as fa
from bistharness.analytics import sector
from bistharness.analytics.events import EVENT_SPECS
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import Direction, FundamentalTemplate

VARIANTS = ("A_TECH", "B_TECH_SECTOR", "C_TECH_SECTOR_FUND", "D_FULL_STRUCTURED", "E_FULL_CONTEXTUAL")
LAYERS: dict[str, tuple[str, ...]] = {
    "A_TECH": (),
    "B_TECH_SECTOR": ("sector",),
    "C_TECH_SECTOR_FUND": ("sector", "fundamental"),
    "D_FULL_STRUCTURED": ("sector", "fundamental", "macro"),
    "E_FULL_CONTEXTUAL": ("sector", "fundamental", "macro", "news"),
}


@dataclass(frozen=True)
class StrategySpec:
    name: str = "REVERSAL_PRESET_V1"
    entry_events: tuple[str, ...] = (
        "BB_LOWER_REVERSAL",
        "RSI_TROUGH_VOLUME",
        "SUPERTREND_BULLISH_FLIP",
        "SUPPORT_TOUCH",
    )
    require_volume_rise: bool = False
    holding_days: int = 5
    sector_window: int = 20
    sector_max_lag: float = 0.0
    fund_min_topline_growth: float = 0.0
    macro_max_fx_change: float = 0.05
    macro_fx_window: int = 21
    macro_hike_lookback_days: int = 30
    news_block_topics: tuple[str, ...] = ("regulation", "geopolitics")
    news_lookback_days: int = 2
    # Scenario 2: when set, the entry is the weekday condition instead of technical events: signal at the close of
    # the last condition day when every condition day of that ISO week has the required return sign.
    weekday_condition: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        days = {"Mon", "Tue", "Wed", "Thu", "Fri"}
        if any(d not in days or s not in (1, -1) for d, s in self.weekday_condition):
            raise ValueError("weekday_condition items must be (Mon..Fri, +1/-1)")
        bad = [
            e for e in self.entry_events if e not in EVENT_SPECS or EVENT_SPECS[e].direction is not Direction.BULLISH
        ]
        if bad:
            raise ValueError(f"entry events must be bullish event types (long only): {bad}")
        if not self.entry_events:
            raise ValueError("at least one entry event is required")


def _end_of_day(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return days + pd.Timedelta(hours=23, minutes=59, seconds=59)


def technical_entries(
    flags: Mapping[str, pd.DataFrame],
    indicators: Mapping[str, pd.DataFrame],
    spec: StrategySpec,
    days: pd.DatetimeIndex,
) -> pd.DataFrame:
    out = {}
    for tk, f in flags.items():
        m = f[list(spec.entry_events)].any(axis=1)
        if spec.require_volume_rise:
            m &= indicators[tk]["volume_rise"].astype(bool)
        out[tk] = m.reindex(days, fill_value=False)
    return pd.DataFrame(out, index=days).fillna(False).astype(bool)


_DAY_NUM = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}


def weekday_entries(closes: Mapping[str, pd.Series], spec: StrategySpec, days: pd.DatetimeIndex) -> pd.DataFrame:
    """Signal on the last condition day's close when all condition days of the same ISO week match their signs."""
    cond = sorted(spec.weekday_condition, key=lambda x: _DAY_NUM[x[0]])
    last_day = _DAY_NUM[cond[-1][0]]
    out = {}
    for tk, c in closes.items():
        r = c.pct_change()
        iso = r.index.isocalendar()
        frame = pd.DataFrame(
            {"r": r.to_numpy(), "wd": r.index.day_of_week, "y": iso["year"].to_numpy(), "w": iso["week"].to_numpy()},
            index=r.index,
        )
        sig = pd.Series(False, index=r.index)
        for _, wk in frame.groupby(["y", "w"]):
            ok = True
            for d, s in cond:
                v = wk.loc[wk["wd"] == _DAY_NUM[d], "r"]
                if v.empty or pd.isna(v.iloc[0]) or (v.iloc[0] > 0) != (s > 0) or v.iloc[0] == 0:
                    ok = False
                    break
            last = wk.index[wk["wd"] == last_day]
            if ok and len(last):
                sig.loc[last[0]] = True
        out[tk] = sig.reindex(days, fill_value=False)
    return pd.DataFrame(out, index=days).fillna(False).astype(bool)


def sector_mask(
    group_closes: pd.DataFrame, ticker: str, calendar: TradingCalendar, benchmark: pd.Series | None, spec: StrategySpec
) -> pd.Series:
    """Stock trails its peers (leave-one-out median) over sector_window while the whole group is strong."""
    p = sector.SectorParams(lag_window=spec.sector_window)
    cl = sector.aligned_closes(group_closes, calendar)
    if cl.shape[1] < 2 or ticker not in cl.columns:
        return pd.Series(False, index=cl.index)
    r = sector.trailing_returns(cl, spec.sector_window)
    others = r.drop(columns=[ticker]).median(axis=1, skipna=True)
    lag = r[ticker] - others
    br = None
    if benchmark is not None:
        b = benchmark.reindex(cl.index)
        br = b / b.shift(spec.sector_window) - 1
    strong = r.median(axis=1, skipna=True) > p.strong_sector_min
    if br is not None:
        strong &= r.median(axis=1, skipna=True) > br
    return ((lag <= spec.sector_max_lag) & strong & lag.notna()).astype(bool)


def fundamental_timeline(
    rows: pd.DataFrame, ticker: str, template: FundamentalTemplate, spec: StrategySpec
) -> pd.DataFrame:
    """One row per KAP disclosure: knowledge time, fiscal period and whether it passes the C-layer rule."""
    if rows.empty:
        return pd.DataFrame(columns=["disclosure_datetime", "fiscal_period", "ok", "topline_yoy", "profit_up"])
    fmt = fa.statement_format(template)
    top = fa.LEVEL_METRICS[fmt][0]
    out = []
    for idx, grp in rows.groupby("disclosure_index", sort=True):
        reps = fa.build_reports(grp, ticker=ticker)
        if not reps:
            continue
        rep = reps[max(reps)]
        g, _ = fa.growth(rep.ytd.get(top), rep.prior_ytd.get(top))
        ni, ni_prior = rep.ytd.get("net_income_parent"), rep.prior_ytd.get("net_income_parent")
        profit_up = ni is not None and ni_prior is not None and ni > ni_prior
        ok = g is not None and g > spec.fund_min_topline_growth and profit_up
        out.append(
            {
                "disclosure_datetime": rep.disclosure_datetime,
                "disclosure_index": int(idx),
                "scope": rep.scope,
                "fiscal_period": rep.fiscal_period,
                "ok": bool(ok),
                "topline_yoy": g,
                "profit_up": profit_up,
            }
        )
    df = pd.DataFrame(out)
    # prefer consolidated disclosures when both scopes exist for a fiscal period
    if not df.empty and (df["scope"] == "consolidated").any():
        has_cons = set(df.loc[df["scope"] == "consolidated", "fiscal_period"])
        df = df[(df["scope"] == "consolidated") | ~df["fiscal_period"].isin(has_cons)]
    return df.sort_values(["disclosure_datetime", "disclosure_index"]).reset_index(drop=True)


def fundamental_mask(timeline: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    """On day d: the newest fiscal period disclosed by d 23:59:59 (its latest version) must pass the rule."""
    out = np.zeros(len(days), dtype=bool)
    if timeline.empty:
        return pd.Series(out, index=days)
    known = pd.to_datetime(timeline["disclosure_datetime"]).to_numpy()
    eod = _end_of_day(days).to_numpy()
    for i, t in enumerate(eod):
        vis = timeline[known <= t]
        if vis.empty:
            continue
        latest_fp = vis["fiscal_period"].max()
        out[i] = bool(vis[vis["fiscal_period"] == latest_fp].iloc[-1]["ok"])
    return pd.Series(out, index=days)


def known_step(df: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    """Value of a release-dated series known at each day's end: among rows released by then, the one with the
    latest obs_date."""
    if df.empty:
        return pd.Series(np.nan, index=days)
    d = df.assign(rel=pd.to_datetime(df["release_datetime"]), obs=pd.to_datetime(df["obs_date"]))
    d = d.sort_values(["rel", "obs"]).reset_index(drop=True)
    obs = d["obs"].to_numpy()
    # index of the latest observation among the first k released rows
    best = np.zeros(len(d), dtype=int)
    for k in range(1, len(d)):
        best[k] = k if obs[k] >= obs[best[k - 1]] else best[k - 1]
    k = np.searchsorted(d["rel"].to_numpy(), _end_of_day(days).to_numpy(), side="right")
    vals = np.where(k > 0, d["value"].to_numpy(dtype=float)[best[np.maximum(k - 1, 0)]], np.nan)
    return pd.Series(vals, index=days)


def macro_mask(macro: pd.DataFrame, days: pd.DatetimeIndex, spec: StrategySpec) -> pd.Series:
    """True = no macro stress known that day (see module docstring)."""
    fx = known_step(macro[macro["series_code"] == "USDTRY"], days)
    change = fx / fx.shift(spec.macro_fx_window) - 1
    fx_shock = (change > spec.macro_max_fx_change).fillna(False)
    pr = macro[macro["series_code"] == "TCMB_POLICY_RATE"].sort_values("obs_date")
    pr = pr.assign(previous=pr["value"].shift(1))
    hikes = pd.to_datetime(pr.loc[pr["previous"].notna() & (pr["value"] > pr["previous"]), "release_datetime"])
    eod = _end_of_day(days)
    recent = np.zeros(len(days), dtype=bool)
    window = pd.Timedelta(days=spec.macro_hike_lookback_days)
    for h in hikes:
        recent |= (eod >= h) & (eod - window < h)
    return pd.Series(~(fx_shock.to_numpy() | recent), index=days)


def news_mask(news: pd.DataFrame, ticker: str, days: pd.DatetimeIndex, spec: StrategySpec) -> pd.Series:
    """True = no event-risk news for the ticker published in the last `news_lookback_days` trading days."""
    ok = np.ones(len(days), dtype=bool)
    if news.empty:
        return pd.Series(ok, index=days)
    block = set(spec.news_block_topics)
    hits = []
    for pub, tks, tps in zip(news["published_at"], news["tickers"], news["topics"], strict=True):
        if ticker in json.loads(tks or "[]") and block & set(json.loads(tps or "[]")):
            hits.append(pd.Timestamp(pub))
    if not hits:
        return pd.Series(ok, index=days)
    eod = _end_of_day(days)
    for i in range(len(days)):
        lo = days[max(0, i - spec.news_lookback_days)]
        ok[i] = not any(lo <= h <= eod[i] for h in hits)
    return pd.Series(ok, index=days)


def apply_variant(entries: pd.DataFrame, masks: Mapping[str, pd.DataFrame], variant: str) -> pd.DataFrame:
    if variant not in LAYERS:
        raise ValueError(f"unknown variant {variant}; expected one of {VARIANTS}")
    out = entries.copy()
    for layer in LAYERS[variant]:
        out &= masks[layer].reindex_like(out).fillna(False).astype(bool)
    return out


def signal_dates(combined: pd.DataFrame, start: pd.Timestamp) -> dict[str, list[pd.Timestamp]]:
    return {tk: [d for d in combined.index[combined[tk].to_numpy()] if d >= start] for tk in combined.columns}


def layer_names(variant: str) -> Sequence[str]:
    return LAYERS[variant]
