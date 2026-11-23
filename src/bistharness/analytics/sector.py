"""Scenario 1 — sector relative strength, laggards and catch-up (pure, point-in-time).

Definitions (w = trailing window in trading days, all quantities known at the close of t):
- r_i(w)          = close_i(t) / close_i(t-w) - 1 on the as_of-truncated trading calendar.
- peer median     = median of r_j(w) over the OTHER members of i's peer group (leave-one-out, so a stock never
                    pulls its own benchmark; the specification's "stock return minus sector-median return").
- lag_score_i(w)  = r_i(w) - peer median (percentage points as a fraction; -0.085 = 8.5 pp behind).
- rank            = 1 for the best r(w) in the group.
- strong sector   = median r(w) of the whole group > strong_sector_min AND > benchmark r(w) (if a benchmark is given).
- laggard at t    = lag_score(lag_window) <= lag_threshold while the sector is strong.
- event           = ENTRY into the laggard state (laggard at t, not at t-1) -> one event per episode, not per day.
- catch-up outcome over h = r_i(t -> t+h) - mean_j r_j(t -> t+h) over the other members (equal-weighted basket);
                    success = outcome > 0, false positive = outcome <= 0 (the laggard kept underperforming).
- persistent lag  = lag_score is also <= lag_threshold over every `structural_windows` window -> structural-laggard
                    candidate (needs fundamental/macro evidence to separate from a temporary laggard).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from bistharness.analytics import stats
from bistharness.analytics.forward_returns import CalendarIndex, StudyParams, sample_warnings
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import Severity, WarningCode
from bistharness.core.schemas import ExcludedEvent, WarningItem


@dataclass(frozen=True)
class SectorParams:
    windows: tuple[int, ...] = (5, 10, 20, 60)
    lag_window: int = 20
    lag_threshold: float = -0.05
    strong_sector_min: float = 0.0
    structural_windows: tuple[int, ...] = (60, 120)
    horizons: tuple[int, ...] = (5, 10, 20)
    small_group: int = 3  # settings.thresholds.small_sector_group


def aligned_closes(closes: pd.DataFrame, calendar: TradingCalendar) -> pd.DataFrame:
    """date x ticker closes on the as_of-truncated trading calendar (missing bars stay NaN)."""
    cal = CalendarIndex(calendar)
    return closes.reindex(cal.days)


def trailing_returns(closes: pd.DataFrame, window: int) -> pd.DataFrame:
    return closes / closes.shift(window) - 1


def _leave_one_out_median(r: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=r.index, columns=r.columns, dtype=float)
    for t in r.columns:
        out[t] = r.drop(columns=[t]).median(axis=1, skipna=True)
    return out


def _strong(r: pd.DataFrame, bench_r: pd.Series | None, p: SectorParams) -> pd.Series:
    med = r.median(axis=1, skipna=True)
    strong = med > p.strong_sector_min
    if bench_r is not None:
        strong &= med > bench_r.reindex(r.index)
    return strong


@dataclass(frozen=True)
class MemberSnapshot:
    ticker: str
    window: int
    ret: float | None
    peer_median: float | None
    lag_score: float | None
    rank: int | None
    rel_benchmark: float | None


@dataclass
class SectorSnapshot:
    group: str
    as_of: date
    members: tuple[str, ...]
    members_with_data: tuple[str, ...]
    benchmark_returns: dict[int, float | None]
    group_median: dict[int, float | None]
    strong: dict[int, bool]
    rows: list[MemberSnapshot]
    laggards: list[str]  # lag_window laggards in a strong sector at as_of
    leaders: list[str]  # rank 1 at lag_window
    persistent_laggards: list[str]
    warnings: list[WarningItem] = field(default_factory=list)


def _val(x: float) -> float | None:
    return None if x is None or not np.isfinite(x) else float(x)


def sector_snapshot(
    closes: pd.DataFrame,
    *,
    group: str,
    calendar: TradingCalendar,
    benchmark: pd.Series | None = None,
    params: SectorParams | None = None,
) -> SectorSnapshot:
    """Relative strength of every member of one peer group at the last calendar day (= as_of)."""
    p = params or SectorParams()
    cl = aligned_closes(closes, calendar)
    t = cl.index[-1]
    bench = benchmark.reindex(cl.index) if benchmark is not None else None
    with_data = tuple(c for c in cl.columns if pd.notna(cl.at[t, c]))
    warnings: list[WarningItem] = []
    if len(with_data) < p.small_group:
        warnings.append(
            WarningItem(
                code=WarningCode.SMALL_SECTOR_GROUP,
                severity=Severity.SOFT,
                detail=f"{group}: {len(with_data)} member(s) with a price at {t.date()} (< {p.small_group})",
            )
        )
    rows: list[MemberSnapshot] = []
    bench_r: dict[int, float | None] = {}
    med_r: dict[int, float | None] = {}
    strong: dict[int, bool] = {}
    lag_now: dict[int, pd.Series] = {}
    windows = sorted(set(p.windows) | {p.lag_window} | set(p.structural_windows))
    for w in windows:
        r = trailing_returns(cl, w)
        br = trailing_returns(bench.to_frame("b"), w)["b"] if bench is not None else None
        loo = _leave_one_out_median(r)
        lag = (r - loo).loc[t]
        lag_now[w] = lag
        bench_r[w] = _val(br.loc[t]) if br is not None else None
        med_r[w] = _val(r.loc[t].median(skipna=True))
        strong[w] = bool(_strong(r.loc[[t]], br.loc[[t]] if br is not None else None, p).iloc[0])
        ranks = r.loc[t].rank(ascending=False, method="min")
        if w in p.windows or w == p.lag_window:
            bw = bench_r[w]
            for tk in cl.columns:
                rv = _val(r.at[t, tk])
                rows.append(
                    MemberSnapshot(
                        ticker=tk,
                        window=w,
                        ret=rv,
                        peer_median=_val(loo.at[t, tk]),
                        lag_score=_val(lag[tk]),
                        rank=int(ranks[tk]) if pd.notna(ranks[tk]) else None,
                        rel_benchmark=None if rv is None or bw is None else rv - bw,
                    )
                )
    lw = p.lag_window
    lag_ok = lag_now[lw] <= p.lag_threshold
    laggards = sorted(tk for tk in cl.columns if strong[lw] and bool(lag_ok.get(tk, False)))
    persistent = sorted(
        tk for tk in laggards if all(bool(lag_now[w].get(tk, np.nan) <= p.lag_threshold) for w in p.structural_windows)
    )
    rank_lw = [m for m in rows if m.window == lw and m.rank == 1]
    return SectorSnapshot(
        group=group,
        as_of=calendar.as_of,
        members=tuple(cl.columns),
        members_with_data=with_data,
        benchmark_returns={w: bench_r[w] for w in windows},
        group_median={w: med_r[w] for w in windows},
        strong={w: strong[w] for w in windows},
        rows=sorted(rows, key=lambda m: (m.window, m.rank if m.rank is not None else 10**6, m.ticker)),
        laggards=laggards,
        leaders=sorted(m.ticker for m in rank_lw),
        persistent_laggards=persistent,
        warnings=warnings,
    )


def laggard_state(
    closes: pd.DataFrame, calendar: TradingCalendar, benchmark: pd.Series | None, params: SectorParams | None = None
) -> pd.DataFrame:
    """date x ticker boolean: laggard in a strong sector at that day's close (one peer group per call)."""
    p = params or SectorParams()
    cl = aligned_closes(closes, calendar)
    r = trailing_returns(cl, p.lag_window)
    br = (
        trailing_returns(benchmark.reindex(cl.index).to_frame("b"), p.lag_window)["b"]
        if benchmark is not None
        else None
    )
    lag = r - _leave_one_out_median(r)
    strong = _strong(r, br, p)
    return (lag <= p.lag_threshold).mul(strong, axis=0) & lag.notna()


def entry_events(state: pd.DataFrame) -> dict[str, list[pd.Timestamp]]:
    prev = state.shift(1, fill_value=False).astype(bool)
    entries = state.astype(bool) & ~prev
    return {tk: list(entries.index[entries[tk].to_numpy()]) for tk in state.columns}


@dataclass(frozen=True)
class CatchUpHorizon:
    horizon: int
    n: int
    n_catch_up: int
    n_false_positive: int
    hit_rate: float | None
    hit_rate_ci95: tuple[float, float] | None
    mean_relative: float | None
    median_relative: float | None  # "median catch-up size"
    p_mean_zero: float | None
    baseline_n: int
    baseline_hit_rate: float | None
    p_rate_vs_baseline: float | None


@dataclass
class CatchUpStudy:
    groups: tuple[str, ...]
    start: date
    as_of: date
    n_events: int
    horizons: list[CatchUpHorizon]
    events: pd.DataFrame  # ticker, group, event_date, lag_score, rel_{h}d
    false_positives: pd.DataFrame  # events whose main-horizon relative return <= 0
    excluded: list[ExcludedEvent]
    warnings: list[WarningItem]


def catch_up_study(
    group_closes: Mapping[str, pd.DataFrame],
    calendar: TradingCalendar,
    *,
    start: date,
    end: date | None = None,
    benchmark: pd.Series | None = None,
    params: SectorParams | None = None,
    study: StudyParams | None = None,
    main_horizon: int = 20,
) -> CatchUpStudy:
    """Historical test of 'laggards in strong sectors catch up', pooled over the given peer groups.

    Entry events are taken in [start, end] (end defaults to as_of); their outcomes may use data up to as_of."""
    p = params or SectorParams()
    sp = study or StudyParams(horizons=p.horizons)
    cal = CalendarIndex(calendar)
    n_days = len(cal)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end or calendar.as_of)
    event_rows: list[dict[str, object]] = []
    n_entries = 0
    excluded: list[ExcludedEvent] = []
    base: dict[int, list[float]] = {h: [] for h in p.horizons}
    for group, closes in group_closes.items():
        cl = aligned_closes(closes, calendar)
        if cl.shape[1] < 2:
            continue
        values = cl.to_numpy(dtype=float)
        state = laggard_state(closes, calendar, benchmark, p)
        lag = trailing_returns(cl, p.lag_window)
        lag = lag - _leave_one_out_median(lag)
        entries = entry_events(state)
        n_entries += sum(1 for dates in entries.values() for d in dates if start_ts <= d <= end_ts)
        for h in p.horizons:
            fwd = np.full_like(values, np.nan)
            if n_days > h:
                fwd[:-h] = values[h:] / values[:-h] - 1
            rel = np.full_like(fwd, np.nan)
            for j in range(fwd.shape[1]):
                others = np.delete(fwd, j, axis=1)
                cnt = (~np.isnan(others)).sum(axis=1)
                basket = np.where(cnt > 0, np.nansum(others, axis=1) / np.maximum(cnt, 1), np.nan)
                rel[:, j] = fwd[:, j] - basket
            rel_df = pd.DataFrame(rel, index=cl.index, columns=cl.columns)
            in_window = (rel_df.index >= start_ts) & (rel_df.index <= end_ts)
            mask = in_window[:, None] & ~state.to_numpy(dtype=bool)
            base[h].extend(rel_df.to_numpy()[mask & ~np.isnan(rel_df.to_numpy())].tolist())
            for tk, dates in entries.items():
                for d in dates:
                    if d < start_ts or d > end_ts:
                        continue
                    i = cal.position(d)
                    assert i is not None
                    if i + h >= n_days or np.isnan(rel_df.at[d, tk]):
                        reason = WarningCode.FORWARD_WINDOW_INCOMPLETE if i + h >= n_days else WarningCode.PRICE_MISSING
                        excluded.append(
                            ExcludedEvent(
                                event_date=d.date(),
                                horizon=h,
                                trading_days_available=min(n_days - 1 - i, h),
                                reason=reason.value,
                                event_type="SECTOR_LAGGARD_ENTRY",
                                ticker=tk,
                            )
                        )
                        continue
                    event_rows.append(
                        {
                            "ticker": tk,
                            "group": group,
                            "event_date": d,
                            "lag_score": float(lag.at[d, tk]),
                            "horizon": h,
                            "relative": float(rel_df.at[d, tk]),
                        }
                    )
    ev = pd.DataFrame(event_rows, columns=["ticker", "group", "event_date", "lag_score", "horizon", "relative"])
    out: list[CatchUpHorizon] = []
    warnings: list[WarningItem] = []
    for h in p.horizons:
        x = ev.loc[ev["horizon"] == h, "relative"].to_numpy(dtype=float)
        n, k = len(x), int((x > 0).sum())
        b = np.asarray(base[h], dtype=float)
        b_rate = float((b > 0).mean()) if len(b) else None
        summ = stats.summarize(x)
        out.append(
            CatchUpHorizon(
                horizon=h,
                n=n,
                n_catch_up=k,
                n_false_positive=n - k,
                hit_rate=k / n if n else None,
                hit_rate_ci95=stats.wilson_interval(k, n),
                mean_relative=summ.mean,
                median_relative=summ.median,
                p_mean_zero=stats.t_test_mean(x).p_value,
                baseline_n=len(b),
                baseline_hit_rate=b_rate,
                p_rate_vs_baseline=stats.binomial_test(k, n, b_rate).p_value if b_rate is not None else None,
            )
        )
        warnings.extend(sample_warnings(n, sp, f"SECTOR_LAGGARD_ENTRY h={h}"))
    wide = (
        ev.pivot_table(index=["ticker", "group", "event_date", "lag_score"], columns="horizon", values="relative")
        .rename(columns=lambda h: f"rel_{h}d")
        .reset_index()
        if not ev.empty
        else pd.DataFrame(columns=["ticker", "group", "event_date", "lag_score"])
    )
    main_col = f"rel_{main_horizon}d"
    fp = wide[wide[main_col] <= 0] if main_col in wide.columns else wide.iloc[0:0]
    return CatchUpStudy(
        groups=tuple(group_closes),
        start=start,
        as_of=calendar.as_of,
        n_events=n_entries,
        horizons=out,
        events=wide.sort_values(["event_date", "ticker"], kind="stable").reset_index(drop=True),
        false_positives=fp.sort_values(["event_date", "ticker"], kind="stable").reset_index(drop=True),
        excluded=excluded,
        warnings=warnings,
    )


def rank_universe(snapshots: Sequence[SectorSnapshot], window: int) -> pd.DataFrame:
    """Flatten several group snapshots into one table for a window (ticker, group, ret, peer_median, lag, rank)."""
    rows = [{"group": s.group, **m.__dict__} for s in snapshots for m in s.rows if m.window == window]
    return pd.DataFrame(rows).sort_values(["group", "rank", "ticker"], kind="stable").reset_index(drop=True)
