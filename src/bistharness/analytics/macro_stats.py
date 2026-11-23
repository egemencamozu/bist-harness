"""Macro context and macro-price relationships known at as_of (pure).

Input rows come from PITRepository.macro(...): columns series_code, obs_date, value, release_datetime — only values
released by as_of. Level series (policy rate, Fed target, CPI) are step functions: the value at day d is the last
observation with obs_date <= d. FX is the TCMB indicative buying rate (published 15:30), so daily stock-FX returns are
not synchronous with the 18:10 close; relationships are therefore measured on weekly (Friday) returns by default.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from bistharness.analytics import stats
from bistharness.core.enums import Severity, WarningCode
from bistharness.core.schemas import WarningItem

DAILY_SERIES = ("USDTRY", "EURTRY")
STEP_SERIES = ("TCMB_POLICY_RATE", "FED_TARGET_UPPER", "FED_TARGET_LOWER")
MONTHLY_SERIES = ("TUFE_YOY", "TUFE_MOM")
# a series is stale when its newest observation is older than this many calendar days at as_of
STALE_DAYS = {"USDTRY": 7, "EURTRY": 7, "TUFE_YOY": 70, "TUFE_MOM": 70}


@dataclass(frozen=True)
class SeriesPoint:
    series: str
    obs_date: date
    value: float
    release_datetime: str


def _series(df: pd.DataFrame, code: str) -> pd.DataFrame:
    s = df[df["series_code"] == code].copy()
    s["obs_date"] = pd.to_datetime(s["obs_date"])
    return s.sort_values("obs_date").reset_index(drop=True)


def value_at(df: pd.DataFrame, code: str, day: date) -> SeriesPoint | None:
    """Last observation of `code` with obs_date <= day (rows are already release-filtered to as_of)."""
    s = _series(df, code)
    s = s[s["obs_date"] <= pd.Timestamp(day)]
    if s.empty:
        return None
    r = s.iloc[-1]
    return SeriesPoint(code, r["obs_date"].date(), float(r["value"]), str(r["release_datetime"]))


@dataclass
class MacroSnapshot:
    as_of: date
    latest: dict[str, SeriesPoint]
    changes: dict[str, dict[str, float | None]]  # FX: relative change; rates/CPI: difference in percentage points
    real_policy_rate: float | None  # TCMB policy rate - latest CPI YoY (ex-post, percentage points)
    fed_mid: float | None
    warnings: list[WarningItem] = field(default_factory=list)


def _months_ago(d: date, months: int) -> date:
    return (pd.Timestamp(d) - pd.DateOffset(months=months)).date()


def macro_snapshot(df: pd.DataFrame, as_of: date, *, lookbacks: Sequence[int] = (1, 3, 12)) -> MacroSnapshot:
    latest: dict[str, SeriesPoint] = {}
    changes: dict[str, dict[str, float | None]] = {}
    warnings: list[WarningItem] = []
    for code in (*DAILY_SERIES, *STEP_SERIES, *MONTHLY_SERIES):
        now = value_at(df, code, as_of)
        if now is None:
            warnings.append(
                WarningItem(
                    code=WarningCode.MISSING_MACRO,
                    severity=Severity.SOFT,
                    detail=f"{code}: no value released by {as_of}",
                )
            )
            continue
        latest[code] = now
        limit = STALE_DAYS.get(code)
        if limit is not None and (as_of - now.obs_date).days > limit:
            warnings.append(
                WarningItem(
                    code=WarningCode.MISSING_MACRO,
                    severity=Severity.SOFT,
                    detail=f"{code}: latest observation {now.obs_date} is older than {limit} days at {as_of}",
                )
            )
        ch: dict[str, float | None] = {}
        for m in lookbacks:
            # monthly series: compare with the observation m months before the latest one, not before as_of
            ref_day = _months_ago(now.obs_date if code in MONTHLY_SERIES else as_of, m)
            past = value_at(df, code, ref_day)
            if past is None:
                ch[f"{m}m"] = None
            elif code in DAILY_SERIES:
                ch[f"{m}m"] = now.value / past.value - 1
            else:
                ch[f"{m}m"] = now.value - past.value
        changes[code] = ch
    policy, cpi = latest.get("TCMB_POLICY_RATE"), latest.get("TUFE_YOY")
    fu, fl = latest.get("FED_TARGET_UPPER"), latest.get("FED_TARGET_LOWER")
    return MacroSnapshot(
        as_of=as_of,
        latest=latest,
        changes=changes,
        real_policy_rate=policy.value - cpi.value if policy and cpi else None,
        fed_mid=(fu.value + fl.value) / 2 if fu and fl else None,
        warnings=warnings,
    )


def change_points(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """Observations where a step series changed (obs_date, value, previous value, release_datetime)."""
    s = _series(df, code)
    s["previous"] = s["value"].shift(1)
    out = s[s["previous"].notna() & (s["value"] != s["previous"])]
    return out[["obs_date", "value", "previous", "release_datetime"]].reset_index(drop=True)


# ----------------------------------------------------------------------------------------------- relationships
@dataclass(frozen=True)
class FXRelationship:
    series: str
    frequency: str
    start: date | None
    end: date | None
    correlation: stats.Correlation
    beta: stats.OLS  # stock return = alpha + beta * FX return
    stock_return: float | None  # TRY, over the common period
    fx_return: float | None
    stock_return_in_fx: float | None  # (1 + stock) / (1 + fx) - 1


def fx_relationship(
    stock_close: pd.Series,
    fx: pd.Series,
    *,
    series: str = "USDTRY",
    frequency: str = "W-FRI",
    start: date | None = None,
) -> FXRelationship:
    """Correlation/beta of stock vs FX log returns on a common grid (default weekly, last value of each week)."""
    s, f = stock_close.dropna(), fx.dropna()
    if start is not None:
        s, f = s[s.index >= pd.Timestamp(start)], f[f.index >= pd.Timestamp(start)]
    common = s.index.intersection(f.index)
    # period returns are measured close-to-close between the first and last COMMON DAY (the dates the evidence
    # states), not between the first and last weekly bins: the first weekly value is that week's Friday close, so a
    # bin-based return would silently start a few days after the stated start and disagree with other evidence.
    s_day, f_day = s.loc[common], f.loc[common]
    if frequency != "D":
        s, f = s.resample(frequency).last(), f.resample(frequency).last()
    both = pd.concat([s.rename("s"), f.rename("f")], axis=1).dropna()
    rets = np.log(both).diff().dropna()
    corr = stats.correlation(rets["s"].to_numpy(), rets["f"].to_numpy())
    beta = stats.ols_beta(rets["s"].to_numpy(), rets["f"].to_numpy())
    sr: float | None = None
    fr: float | None = None
    in_fx: float | None = None
    first: date | None = None
    last: date | None = None
    if len(both) >= 2 and len(common) >= 2:
        sr = float(s_day.iloc[-1] / s_day.iloc[0] - 1)
        fr = float(f_day.iloc[-1] / f_day.iloc[0] - 1)
        in_fx = (1 + sr) / (1 + fr) - 1
        # actual observation days, not resample bin labels (a Friday label can lie after a mid-week as_of)
        first, last = common.min().date(), common.max().date()
    return FXRelationship(series, frequency, first, last, corr, beta, sr, fr, in_fx)


# ----------------------------------------------------------------------------------------------- inflation
@dataclass(frozen=True)
class Inflation:
    start_month: date
    end_month: date
    months_used: int
    months_expected: int
    cumulative: float | None  # compounded CPI change over the months used

    @property
    def complete(self) -> bool:
        return self.months_used == self.months_expected


def inflation_between(df: pd.DataFrame, start: date, end: date) -> Inflation:
    """Compounded monthly CPI (TUFE_MOM, %) for the calendar months from start's month to end's month inclusive,
    using only months released by as_of (rows are release-filtered)."""
    s = _series(df, "TUFE_MOM")
    m0, m1 = pd.Timestamp(start).to_period("M"), pd.Timestamp(end).to_period("M")
    months = pd.period_range(m0, m1, freq="M")
    s = s[(s["obs_date"].dt.to_period("M") >= m0) & (s["obs_date"].dt.to_period("M") <= m1)]
    used = len(s)
    cum = float(np.prod(1 + s["value"].to_numpy(dtype=float) / 100) - 1) if used else None
    return Inflation(m0.to_timestamp().date(), m1.to_timestamp().date(), used, len(months), cum)


def real_return(nominal: float | None, inflation: Inflation) -> float | None:
    if nominal is None or inflation.cumulative is None or not math.isfinite(nominal):
        return None
    return (1 + nominal) / (1 + inflation.cumulative) - 1
