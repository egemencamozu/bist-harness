"""Scenario 2 — weekday and multi-day patterns (pure).

Condition != outcome (CLAUDE.md §6). A weekday pattern is a CONDITION on some weekdays of an ISO week (e.g. Mon<0,
Tue<0, Wed<0) and an OUTCOME measured on strictly later weekdays of the same week (e.g. compounded Thu-Fri return).
The conditional outcome is compared with the unconditional outcome (all complete weeks) and with the complement
(complete weeks where the condition fails). The reference script's pattern instead requires Thu>0 & Fri>0 inside the
condition, so its "positive Thu-Fri rate" is 100% by construction; the full 5-day sequence is reported here only as
a descriptive frequency (`full_sequence_*`).

Weeks: daily returns (close.pct_change on the instrument's own bars, as the reference) are pivoted by ISO year/week;
a week is complete when all five weekdays have a return. A week belongs to a period when all its days are inside the
period (a week straddling a split belongs to neither). A week whose condition days are known at as_of but whose
outcome days are not yet (as_of mid-week) is reported in `excluded` (FORWARD_WINDOW_INCOMPLETE), never dropped
silently. Holiday weeks are incomplete and are counted in `incomplete_weeks`.

Multiple testing: the family is every sign combination of the condition days (2^k patterns) for the same outcome;
Welch p-values (condition vs complement) of the whole family are Bonferroni/BH adjusted and the target's adjusted
values are reported.

Sequence patterns (not tied to weekdays): N consecutive down/up days or one large move, event at the close of the
last condition day, outcome = forward h-day return under the forward-window rule (forward_returns).
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats as sps

from bistharness.analytics import stats
from bistharness.analytics.forward_returns import (
    HorizonStats,
    StudyParams,
    all_day_forward_returns,
    event_outcomes,
    summarize_outcomes,
)
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import Direction, Severity, WarningCode
from bistharness.core.schemas import ExcludedEvent, WarningItem

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
_DAY_NUM = {d: i for i, d in enumerate(DAYS)}


def daily_returns(close: pd.Series) -> pd.Series:
    """Simple daily returns on the instrument's own bars (first bar dropped), as the reference."""
    return close.pct_change().dropna()


def weekday_statistics(returns: pd.Series) -> pd.DataFrame:
    """Per weekday: n, mean, median, std, positive rate (fractions), one-sample t-test p (mean == 0) + BH."""
    df = pd.DataFrame({"ret": returns.to_numpy(dtype=float)}, index=returns.index)
    df["day"] = [DAYS[d] if d < 5 else None for d in returns.index.day_of_week]
    rows = []
    for day in DAYS:
        x = df.loc[df["day"] == day, "ret"].to_numpy()
        s = stats.summarize(x)
        rows.append(
            {
                "weekday": day,
                "n": s.n,
                "mean": s.mean,
                "median": s.median,
                "std": s.std,
                "positive_rate": s.positive_rate,
                "p_mean_zero": stats.t_test_mean(x).p_value,
            }
        )
    out = pd.DataFrame(rows).set_index("weekday")
    out["p_bh"] = stats.benjamini_hochberg(list(out["p_mean_zero"]))
    return out


def weekday_effect_test(returns: pd.Series) -> dict[str, float | None]:
    """Is there ANY weekday effect? One-way ANOVA and Kruskal-Wallis across the five weekdays."""
    groups = [returns[returns.index.day_of_week == i].to_numpy(dtype=float) for i in range(5)]
    groups = [g[~np.isnan(g)] for g in groups]
    if min(len(g) for g in groups) < 2:
        return {"anova_p": None, "kruskal_p": None}
    return {"anova_p": float(sps.f_oneway(*groups).pvalue), "kruskal_p": float(sps.kruskal(*groups).pvalue)}


def weekly_table(returns: pd.Series) -> pd.DataFrame:
    """One row per ISO week: iso_year, iso_week, Mon..Fri returns (first return per weekday, as the reference),
    week_start/week_end (calendar Monday/Friday), n_days, complete."""
    iso = returns.index.isocalendar()
    df = pd.DataFrame(
        {
            "iso_year": iso["year"].to_numpy(dtype=int),
            "iso_week": iso["week"].to_numpy(dtype=int),
            "day": [DAYS[d] if d < 5 else "Weekend" for d in returns.index.day_of_week],
            "ret": returns.to_numpy(dtype=float),
        }
    )
    df = df[df["day"] != "Weekend"]
    wide = df.pivot_table(index=["iso_year", "iso_week"], columns="day", values="ret", aggfunc="first").reset_index()
    for d in DAYS:
        if d not in wide.columns:
            wide[d] = np.nan
    wide = wide[["iso_year", "iso_week", *DAYS]].copy()
    wide.columns.name = None
    mondays = [date.fromisocalendar(int(y), int(w), 1) for y, w in zip(wide["iso_year"], wide["iso_week"], strict=True)]
    wide["week_start"] = pd.to_datetime(mondays)
    wide["week_end"] = wide["week_start"] + pd.Timedelta(days=4)
    wide["n_days"] = wide[list(DAYS)].notna().sum(axis=1)
    wide["complete"] = wide["n_days"] == 5
    return wide.sort_values(["iso_year", "iso_week"]).reset_index(drop=True)


def compound(df: pd.DataFrame, days: Sequence[str]) -> pd.Series:
    out = pd.Series(1.0, index=df.index)
    for d in days:
        out = out * (1 + df[d])
    return out - 1


@dataclass(frozen=True)
class WeekdayPattern:
    """condition: ((day, sign), ...) with sign +1 (> 0) / -1 (< 0); outcome: later days, compounded."""

    condition: tuple[tuple[str, int], ...]
    outcome: tuple[str, ...]
    name: str = ""
    descriptive_outcome_signs: tuple[tuple[str, int], ...] = ()  # e.g. (("Thu", 1), ("Fri", 1)) -> full sequence
    market_sign: int | None = None  # also require the benchmark's compounded return over the condition days

    def __post_init__(self) -> None:
        cdays = [d for d, _ in self.condition]
        for d in [*cdays, *self.outcome, *(d for d, _ in self.descriptive_outcome_signs)]:
            if d not in _DAY_NUM:
                raise ValueError(f"unknown weekday {d!r}")
        if any(s not in (1, -1) for _, s in self.condition) or (self.market_sign not in (None, 1, -1)):
            raise ValueError("signs must be +1 or -1")
        if not cdays or not self.outcome:
            raise ValueError("a pattern needs at least one condition day and one outcome day")
        if len(set(cdays)) != len(cdays) or len(set(self.outcome)) != len(self.outcome):
            raise ValueError("duplicate weekday in condition or outcome")
        if min(_DAY_NUM[d] for d in self.outcome) <= max(_DAY_NUM[d] for d in cdays):
            raise ValueError("condition must not contain the outcome: outcome days must come after every condition day")

    @property
    def label(self) -> str:
        cond = " ".join(f"{d}{'>' if s > 0 else '<'}0" for d, s in self.condition)
        return self.name or f"[{cond}] -> {'+'.join(self.outcome)}"

    def condition_mask(self, weekly: pd.DataFrame, market_weekly: pd.DataFrame | None = None) -> pd.Series:
        m = pd.Series(True, index=weekly.index)
        for d, s in self.condition:
            m &= weekly[d] > 0 if s > 0 else weekly[d] < 0
        if self.market_sign is not None:
            if market_weekly is None:
                raise ValueError("market_sign needs benchmark returns")
            mk = weekly[["iso_year", "iso_week"]].merge(market_weekly, on=["iso_year", "iso_week"], how="left")
            mc = compound(mk, [d for d, _ in self.condition]).to_numpy()
            m &= pd.Series(mc > 0 if self.market_sign > 0 else mc < 0, index=weekly.index)
        return m


@dataclass(frozen=True)
class OutcomeStats:
    n: int
    mean: float | None
    median: float | None
    std: float | None
    positive_rate: float | None
    mean_after_cost: float | None


def _outcome_stats(x: np.ndarray, cost: float) -> OutcomeStats:
    s = stats.summarize(x)
    return OutcomeStats(s.n, s.mean, s.median, s.std, s.positive_rate, None if s.mean is None else s.mean - cost)


@dataclass
class PatternPeriodResult:
    period: str
    start: date
    end: date
    complete_weeks: int
    incomplete_weeks: int
    condition_weeks: int
    condition_frequency: float | None
    conditional: OutcomeStats
    unconditional: OutcomeStats
    complement: OutcomeStats
    mean_difference: float | None  # conditional - unconditional
    p_welch_vs_complement: float | None
    p_binomial_vs_unconditional: float | None  # positive rate vs unconditional positive rate
    p_permutation_vs_complement: float | None
    bootstrap_mean_ci95: tuple[float, float] | None
    family_size: int
    p_bonferroni: float | None
    p_bh: float | None
    family_rank: int | None  # 1 = smallest family p-value
    full_sequence_count: int | None
    full_sequence_frequency: float | None  # share of complete weeks with condition AND descriptive outcome signs
    matching_weeks: pd.DataFrame
    warnings: list[WarningItem] = field(default_factory=list)


@dataclass
class PatternTest:
    pattern: WeekdayPattern
    cost: float
    periods: list[PatternPeriodResult]
    excluded: list[ExcludedEvent]


def _sign_family(pattern: WeekdayPattern) -> list[WeekdayPattern]:
    days = [d for d, _ in pattern.condition]
    return [
        WeekdayPattern(tuple(zip(days, signs, strict=True)), pattern.outcome, market_sign=pattern.market_sign)
        for signs in itertools.product((-1, 1), repeat=len(days))
    ]


def evaluate_weekday_pattern(
    returns: pd.Series,
    pattern: WeekdayPattern,
    *,
    periods: Mapping[str, tuple[date, date]],
    as_of: date,
    cost: float = 0.001,
    benchmark_returns: pd.Series | None = None,
    include_weeks: frozenset[tuple[int, int]] | None = None,
    study: StudyParams | None = None,
    seed: int = 42,
) -> PatternTest:
    """Condition/outcome test of one weekday pattern in each period (e.g. {"in_sample": ..., "out_of_sample": ...})."""
    sp = study or StudyParams()
    returns = returns[returns.index <= pd.Timestamp(as_of)]
    weekly = weekly_table(returns)
    market_weekly = (
        weekly_table(benchmark_returns[benchmark_returns.index <= pd.Timestamp(as_of)])
        if benchmark_returns is not None
        else None
    )
    if include_weeks is not None:
        keep = [(int(y), int(w)) in include_weeks for y, w in zip(weekly["iso_year"], weekly["iso_week"], strict=True)]
        weekly = weekly[keep].reset_index(drop=True)
    cdays = [d for d, _ in pattern.condition]
    family = _sign_family(pattern)
    target_idx = next(i for i, f in enumerate(family) if f.condition == pattern.condition)

    # current week: condition known, outcome not yet -> explicit exclusion
    excluded: list[ExcludedEvent] = []
    if len(weekly):
        last = weekly.iloc[-1]
        cond_known = all(pd.notna(last[d]) for d in cdays)
        outcome_missing = any(pd.isna(last[d]) for d in pattern.outcome)
        future = pd.Timestamp(last["week_end"]) > pd.Timestamp(as_of)
        if (
            cond_known
            and outcome_missing
            and future
            and bool(pattern.condition_mask(weekly.iloc[[-1]], market_weekly).iloc[0])
        ):
            excluded.append(
                ExcludedEvent(
                    event_date=pd.Timestamp(last["week_start"]).date(),
                    horizon=len(pattern.outcome),
                    trading_days_available=int(sum(pd.notna(last[d]) for d in pattern.outcome)),
                    event_type=f"WEEKDAY_PATTERN {pattern.label}",
                )
            )

    results: list[PatternPeriodResult] = []
    for label, (start, end) in periods.items():
        end = min(end, as_of)
        inside = (weekly["week_start"] >= pd.Timestamp(start)) & (weekly["week_end"] <= pd.Timestamp(end))
        wk = weekly[inside].reset_index(drop=True)
        comp = wk[wk["complete"]].reset_index(drop=True)
        outcome = compound(comp, pattern.outcome).to_numpy(dtype=float)
        cond = pattern.condition_mask(comp, market_weekly).to_numpy(dtype=bool)
        x, rest = outcome[cond], outcome[~cond]
        # family p-values (condition vs complement) for multiple-testing adjustment
        fam_p = []
        for f in family:
            m = f.condition_mask(comp, market_weekly).to_numpy(dtype=bool)
            fam_p.append(stats.welch_t_test(outcome[m], outcome[~m]).p_value)
        bonf, bh = stats.bonferroni(fam_p), stats.benjamini_hochberg(fam_p)
        valid = sorted((p, i) for i, p in enumerate(fam_p) if p is not None)
        rank = next((r + 1 for r, (_, i) in enumerate(valid) if i == target_idx), None)
        uncond = _outcome_stats(outcome, cost)
        full_count = full_freq = None
        if pattern.descriptive_outcome_signs:
            full = cond.copy()
            for d, s in pattern.descriptive_outcome_signs:
                full &= (comp[d] > 0).to_numpy() if s > 0 else (comp[d] < 0).to_numpy()
            full_count = int(full.sum())
            full_freq = full_count / len(comp) if len(comp) else None
        matching = comp[cond].copy()
        matching["outcome"] = x
        w: list[WarningItem] = []
        w += _sample_warning(len(x), sp, f"{pattern.label} {label}")
        if len(family) > 1:
            w.append(
                WarningItem(
                    code=WarningCode.MULTIPLE_TESTING_RISK,
                    severity=Severity.INFO,
                    detail=f"{label}: family of {len(family)} sign combinations; adjusted p reported",
                )
            )
        results.append(
            PatternPeriodResult(
                period=label,
                start=start,
                end=end,
                complete_weeks=len(comp),
                incomplete_weeks=int((~wk["complete"]).sum()),
                condition_weeks=int(cond.sum()),
                condition_frequency=float(cond.mean()) if len(comp) else None,
                conditional=_outcome_stats(x, cost),
                unconditional=uncond,
                complement=_outcome_stats(rest, cost),
                mean_difference=None if len(x) == 0 or uncond.mean is None else float(np.mean(x)) - uncond.mean,
                p_welch_vs_complement=stats.welch_t_test(x, rest).p_value,
                p_binomial_vs_unconditional=stats.binomial_test(
                    int((x > 0).sum()), len(x), uncond.positive_rate
                ).p_value
                if uncond.positive_rate is not None and len(x)
                else None,
                p_permutation_vs_complement=stats.permutation_test_mean_diff(x, rest, seed=seed).p_value,
                bootstrap_mean_ci95=stats.bootstrap_mean_ci(x, seed=seed),
                family_size=len(family),
                p_bonferroni=bonf[target_idx],
                p_bh=bh[target_idx],
                family_rank=rank,
                full_sequence_count=full_count,
                full_sequence_frequency=full_freq,
                matching_weeks=matching.reset_index(drop=True),
                warnings=w,
            )
        )
    return PatternTest(pattern=pattern, cost=cost, periods=results, excluded=excluded)


def _sample_warning(n: int, sp: StudyParams, label: str) -> list[WarningItem]:
    if n < sp.insufficient_sample:
        return [WarningItem(code=WarningCode.INSUFFICIENT_SAMPLE, detail=f"{label}: n={n}")]
    if n < sp.small_sample:
        return [WarningItem(code=WarningCode.SMALL_SAMPLE, detail=f"{label}: n={n}")]
    return []


# ----------------------------------------------------------------------------------------------- sequences
@dataclass(frozen=True)
class SequencePattern:
    """kind: consecutive_down | consecutive_up (length days) | large_down | large_up (|r| > threshold)."""

    kind: str
    length: int = 3
    threshold: float = 0.03

    def __post_init__(self) -> None:
        if self.kind not in ("consecutive_down", "consecutive_up", "large_down", "large_up"):
            raise ValueError(f"unknown sequence kind {self.kind!r}")
        if self.length < 1 or self.threshold <= 0:
            raise ValueError("length >= 1 and threshold > 0 required")

    @property
    def label(self) -> str:
        if self.kind.startswith("consecutive"):
            return f"{self.length} consecutive {'down' if self.kind.endswith('down') else 'up'} days"
        return f"daily move {'<' if self.kind == 'large_down' else '>'} {'-' if self.kind == 'large_down' else '+'}{self.threshold:.1%}"

    @property
    def label_tr(self) -> str:
        if self.kind == "consecutive_down":
            return f"art arda {self.length} düşüş günü"
        if self.kind == "consecutive_up":
            return f"art arda {self.length} yükseliş günü"
        word = "düşüş" if self.kind == "large_down" else "yükseliş"
        return f"%{self.threshold * 100:.0f}'ten büyük günlük {word}"

    @property
    def direction(self) -> Direction:
        """Hypothesis tested: mean reversion (a down condition is expected to rebound)."""
        return Direction.BULLISH if self.kind.endswith("down") else Direction.BEARISH

    def events(self, returns: pd.Series) -> pd.DatetimeIndex:
        r = returns
        if self.kind == "consecutive_down":
            m = (r < 0).astype(int).rolling(self.length).sum() == self.length
        elif self.kind == "consecutive_up":
            m = (r > 0).astype(int).rolling(self.length).sum() == self.length
        elif self.kind == "large_down":
            m = r < -self.threshold
        else:
            m = r > self.threshold
        return pd.DatetimeIndex(r.index[m.to_numpy(dtype=bool)])


@dataclass
class SequenceTest:
    pattern: SequencePattern
    start: date
    n_events: int
    horizons: list[HorizonStats]
    excluded: list[ExcludedEvent]
    warnings: list[WarningItem]


def evaluate_sequence_pattern(
    close: pd.Series,
    pattern: SequencePattern,
    calendar: TradingCalendar,
    *,
    start: date,
    end: date | None = None,
    study: StudyParams | None = None,
) -> SequenceTest:
    """Events in [start, end] (end defaults to as_of); outcomes may use data up to as_of."""
    sp = study or StudyParams(horizons=(1, 2, 3, 5))
    ret = daily_returns(close[close.index <= pd.Timestamp(calendar.as_of)])
    ev = pattern.events(ret)
    ev = ev[(ev >= pd.Timestamp(start)) & (ev <= pd.Timestamp(end or calendar.as_of))]
    out = event_outcomes(ev, close, calendar, sp.horizons, direction=pattern.direction, event_type=pattern.label)
    base = all_day_forward_returns(close, calendar, sp.horizons)
    base = base[(base.index >= pd.Timestamp(start)) & (base.index <= pd.Timestamp(end or calendar.as_of))]
    hs, w = summarize_outcomes(out, direction=pattern.direction, params=sp, baseline=base, label=pattern.label)
    return SequenceTest(pattern, start, len(ev), hs, out.excluded, w)
