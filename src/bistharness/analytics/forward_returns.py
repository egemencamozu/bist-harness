"""Forward returns and event studies under the forward-window completeness rule (CLAUDE.md §2).

An event on trading day t is measured over horizon h from close(t) to close(t+h), where t+h is the h-th trading day
of the as_of-truncated calendar after t. If that day is not known at as_of the event is NOT silently dropped: it is
returned in `excluded` (reason FORWARD_WINDOW_INCOMPLETE, with the number of days available). A missing bar of the
instrument on t or t+h (trading halt) is excluded with reason PRICE_MISSING.

Abnormal returns are market-adjusted (no beta estimation): r_stock - r_benchmark over the same window, and
r_stock - mean(r_peer) for an equal-weighted peer basket (the stock itself excluded by the caller).
Reversal strength = maximum favourable excursion within the window: bullish max(high)/close(t) - 1, bearish
1 - min(low)/close(t).

Baseline: the same forward return measured from every trading day that is NOT an event day ("unconditional"
comparison). Overlapping windows inflate t-statistics; `n_independent` reports how many events remain after greedy
thinning to non-overlapping windows.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from bistharness.analytics import stats
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import Direction, Severity, WarningCode
from bistharness.core.schemas import ExcludedEvent, WarningItem


@dataclass(frozen=True)
class StudyParams:
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20)
    success_threshold: float = 0.0  # the reference's "forward return > 0"
    small_sample: int = 10  # settings.thresholds.small_sample
    insufficient_sample: int = 5  # settings.thresholds.insufficient_sample


class CalendarIndex:
    """Positions of the as_of-truncated trading calendar, for vectorised t -> t+h lookups."""

    def __init__(self, calendar: TradingCalendar) -> None:
        self.calendar = calendar
        self.days = pd.DatetimeIndex([pd.Timestamp(d) for d in calendar.days])
        self._pos = {d: i for i, d in enumerate(self.days)}

    def __len__(self) -> int:
        return len(self.days)

    def position(self, d: date | pd.Timestamp) -> int | None:
        return self._pos.get(pd.Timestamp(d))

    def align(self, s: pd.Series) -> np.ndarray:
        """Series values on calendar days (NaN where the instrument has no bar); later days are ignored."""
        return s.reindex(self.days).to_numpy(dtype=float)

    def align_frame(self, df: pd.DataFrame) -> np.ndarray:
        return df.reindex(self.days).to_numpy(dtype=float)


def _to_ts(d: date | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(d).normalize()


@dataclass
class Outcomes:
    """Per-event, per-horizon outcomes (complete windows only) plus the explicit exclusion list."""

    table: pd.DataFrame
    excluded: list[ExcludedEvent] = field(default_factory=list)

    COLUMNS = (
        "event_date",
        "event_pos",  # trading-day ordinal of the event in the calendar (overlap thinning)
        "horizon",
        "end_date",
        "ret",
        "ret_benchmark",
        "abn_benchmark",
        "ret_peers",
        "abn_peers",
        "mfe",
    )


def event_outcomes(
    event_dates: Iterable[date | pd.Timestamp],
    close: pd.Series,
    calendar: TradingCalendar,
    horizons: Sequence[int],
    *,
    direction: Direction = Direction.BULLISH,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    benchmark: pd.Series | None = None,
    peers: pd.DataFrame | None = None,
    event_type: str | None = None,
    ticker: str | None = None,
) -> Outcomes:
    cal = CalendarIndex(calendar)
    c = cal.align(close)
    hi = cal.align(high) if high is not None else None
    lo = cal.align(low) if low is not None else None
    b = cal.align(benchmark) if benchmark is not None else None
    pr = cal.align_frame(peers) if peers is not None and not peers.empty else None
    n = len(cal)
    rows: list[dict[str, object]] = []
    excluded: list[ExcludedEvent] = []

    def exclude(d: pd.Timestamp, h: int, available: int, reason: WarningCode) -> None:
        excluded.append(
            ExcludedEvent(
                event_date=d.date(),
                horizon=h,
                trading_days_available=available,
                reason=reason.value,
                event_type=event_type,
                ticker=ticker,
            )
        )

    for d in sorted({_to_ts(x) for x in event_dates}):
        i = cal.position(d)
        if i is None:
            if d > pd.Timestamp(calendar.as_of):
                raise ValueError(f"event {d.date()} is after as_of {calendar.as_of}")
            raise ValueError(f"event {d.date()} is not a trading day of the calendar")
        for h in sorted(set(horizons)):
            j = i + h
            available = min(n - 1 - i, h)
            if j >= n:
                exclude(d, h, available, WarningCode.FORWARD_WINDOW_INCOMPLETE)
                continue
            if np.isnan(c[i]) or np.isnan(c[j]):
                exclude(d, h, available, WarningCode.PRICE_MISSING)
                continue
            ret = c[j] / c[i] - 1
            rb = b[j] / b[i] - 1 if b is not None else np.nan
            rp = np.nan
            if pr is not None:
                peer_r = pr[j] / pr[i] - 1
                if np.isfinite(peer_r).any():
                    rp = float(np.nanmean(peer_r))
            mfe = np.nan
            if direction is Direction.BULLISH and hi is not None:
                mfe = np.nanmax(hi[i + 1 : j + 1]) / c[i] - 1
            elif direction is Direction.BEARISH and lo is not None:
                mfe = 1 - np.nanmin(lo[i + 1 : j + 1]) / c[i]
            rows.append(
                {
                    "event_date": d,
                    "event_pos": i,
                    "horizon": h,
                    "end_date": cal.days[j],
                    "ret": ret,
                    "ret_benchmark": rb,
                    "abn_benchmark": ret - rb,
                    "ret_peers": rp,
                    "abn_peers": ret - rp,
                    "mfe": mfe,
                }
            )
    table = pd.DataFrame(rows, columns=list(Outcomes.COLUMNS))
    return Outcomes(table=table, excluded=excluded)


def all_day_forward_returns(close: pd.Series, calendar: TradingCalendar, horizons: Sequence[int]) -> pd.DataFrame:
    """Forward h-day return from every calendar day (NaN when the window is incomplete or a bar is missing)."""
    cal = CalendarIndex(calendar)
    c = cal.align(close)
    out = {}
    for h in horizons:
        fwd = np.full(len(c), np.nan)
        if len(c) > h:
            fwd[:-h] = c[h:] / c[:-h] - 1
        out[h] = fwd
    return pd.DataFrame(out, index=cal.days)


@dataclass(frozen=True)
class HorizonStats:
    horizon: int
    n: int
    n_success: int
    success_rate: float | None
    success_rate_ci95: tuple[float, float] | None
    mean: float | None
    median: float | None
    std: float | None
    t_stat: float | None  # H0: mean forward return == 0
    p_value: float | None
    mean_abn_benchmark: float | None
    mean_abn_peers: float | None
    mean_mfe: float | None
    median_mfe: float | None
    n_independent: int
    baseline_n: int | None = None
    baseline_mean: float | None = None
    baseline_success_rate: float | None = None
    p_mean_vs_baseline: float | None = None  # Welch: event windows vs non-event days
    p_rate_vs_baseline: float | None = None  # exact binomial: success rate vs baseline success rate


def is_success(ret: np.ndarray | pd.Series, direction: Direction, threshold: float) -> np.ndarray:
    r = np.asarray(ret, dtype=float)
    return r > threshold if direction is Direction.BULLISH else r < -threshold


def _nanmean(x: np.ndarray) -> float | None:
    x = x[~np.isnan(x)]
    return float(x.mean()) if len(x) else None


def _nanmedian(x: np.ndarray) -> float | None:
    x = x[~np.isnan(x)]
    return float(np.median(x)) if len(x) else None


def summarize_outcomes(
    outcomes: Outcomes,
    *,
    direction: Direction,
    params: StudyParams,
    baseline: pd.DataFrame | None = None,
    label: str = "",
    value_col: str = "ret",
) -> tuple[list[HorizonStats], list[WarningItem]]:
    """Per-horizon statistics of `value_col` ("ret", "abn_benchmark" or "abn_peers").

    `baseline` = the same quantity from every trading day (e.g. all_day_forward_returns) of the same instrument.
    """
    out: list[HorizonStats] = []
    warnings: list[WarningItem] = []
    t = outcomes.table
    hz = t["horizon"].to_numpy()
    val = t[value_col].to_numpy(dtype=float)
    abn_b = t["abn_benchmark"].to_numpy(dtype=float)
    abn_p = t["abn_peers"].to_numpy(dtype=float)
    mfe = t["mfe"].to_numpy(dtype=float)
    pos = t["event_pos"].to_numpy()
    dates = pd.DatetimeIndex(t["event_date"])
    for h in params.horizons:
        m = (hz == h) & ~np.isnan(val)
        r = val[m]
        succ = is_success(r, direction, params.success_threshold)
        n, k = len(r), int(succ.sum())
        summ = stats.summarize(r)
        tt = stats.t_test_mean(r)
        hs = HorizonStats(
            horizon=h,
            n=n,
            n_success=k,
            success_rate=k / n if n else None,
            success_rate_ci95=stats.wilson_interval(k, n),
            mean=summ.mean,
            median=summ.median,
            std=summ.std,
            t_stat=tt.statistic,
            p_value=tt.p_value,
            mean_abn_benchmark=_nanmean(abn_b[m]),
            mean_abn_peers=_nanmean(abn_p[m]),
            mean_mfe=_nanmean(mfe[m]),
            median_mfe=_nanmedian(mfe[m]),
            n_independent=stats.greedy_non_overlapping([int(x) for x in pos[m]], h),
        )
        if baseline is not None and h in baseline.columns:
            col = baseline[h]
            keep = col.notna().to_numpy() & ~col.index.isin(dates[m])
            base = col.to_numpy(dtype=float)[keep]
            bn = len(base)
            b_rate = float(is_success(base, direction, params.success_threshold).mean()) if bn else None
            hs = replace(
                hs,
                baseline_n=bn,
                baseline_mean=float(base.mean()) if bn else None,
                baseline_success_rate=b_rate,
                p_mean_vs_baseline=stats.welch_t_test(r, base).p_value,
                p_rate_vs_baseline=stats.binomial_test(k, n, b_rate).p_value if b_rate is not None else None,
            )
        out.append(hs)
        warnings.extend(sample_warnings(n, params, f"{label} h={h}".strip()))
    return out, warnings


def sample_warnings(n: int, params: StudyParams, label: str) -> list[WarningItem]:
    if n < params.insufficient_sample:
        return [WarningItem(code=WarningCode.INSUFFICIENT_SAMPLE, severity=Severity.SOFT, detail=f"{label}: n={n}")]
    if n < params.small_sample:
        return [WarningItem(code=WarningCode.SMALL_SAMPLE, severity=Severity.SOFT, detail=f"{label}: n={n}")]
    return []
