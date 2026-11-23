"""Scenario 3 aggregation: per event type forward-return statistics, regime/state breakdowns and multiple testing.

Pure: takes indicator/event frames already restricted to data <= as_of plus the as_of-truncated calendar.
Statistics follow forward_returns (completeness rule, explicit exclusions, baseline = non-event days).
Multiple testing: the family is every event type tested in one call; the main-horizon p-values of
"event-window mean == non-event-day mean" (Welch) are adjusted with Bonferroni and Benjamini-Hochberg.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from bistharness.analytics import stats
from bistharness.analytics.events import EVENT_SPECS
from bistharness.analytics.forward_returns import (
    HorizonStats,
    Outcomes,
    StudyParams,
    all_day_forward_returns,
    event_outcomes,
    summarize_outcomes,
)
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import Direction, Severity, WarningCode
from bistharness.core.schemas import ExcludedEvent, WarningItem

BREAKDOWN_COLUMNS = ("market_trend", "volatility", "supertrend_state", "ichimoku_state", "kama_slope_state")


@dataclass(frozen=True)
class EventTypeStudy:
    event_type: str
    family: str
    direction: Direction
    n_events: int  # detected in the window, including events whose forward windows are incomplete
    event_dates: tuple[date, ...]
    horizons: list[HorizonStats]
    breakdowns: dict[str, dict[str, list[HorizonStats]]]  # column -> state value -> per-horizon stats (no baseline)
    excluded: list[ExcludedEvent]
    p_bonferroni: float | None = None
    p_bh: float | None = None


@dataclass
class ReversalStudy:
    ticker: str
    start: date
    as_of: date
    main_horizon: int
    family_size: int
    studies: list[EventTypeStudy]
    records: pd.DataFrame  # one row per event with the market state (and regimes) at the event date
    warnings: list[WarningItem] = field(default_factory=list)

    def study(self, event_type: str) -> EventTypeStudy:
        for s in self.studies:
            if s.event_type == event_type:
                return s
        raise KeyError(event_type)


def reversal_event_study(
    ind: pd.DataFrame,
    flags: pd.DataFrame,
    state: pd.DataFrame,
    calendar: TradingCalendar,
    *,
    ticker: str,
    start: date,
    params: StudyParams | None = None,
    event_types: Sequence[str] | None = None,
    main_horizon: int = 5,
    benchmark: pd.Series | None = None,
    peers: pd.DataFrame | None = None,
    regimes: pd.DataFrame | None = None,
    custom: Mapping[str, tuple[pd.Series, Direction, str]] | None = None,
) -> ReversalStudy:
    """`custom`: extra conditional events name -> (bool flags, direction, family), e.g. a band touch filtered by
    the market state; they join the multiple-testing family."""
    p = params or StudyParams()
    if main_horizon not in p.horizons:
        raise ValueError(f"main_horizon {main_horizon} not in horizons {p.horizons}")
    custom = dict(custom or {})
    specs = {n: (s.direction, s.family) for n, s in EVENT_SPECS.items()} | {
        n: (d, fam) for n, (_, d, fam) in custom.items()
    }
    if custom:
        flags = flags.assign(
            **{n: ser.reindex(flags.index, fill_value=False).astype(bool) for n, (ser, _, _) in custom.items()}
        )
    types = list(event_types or EVENT_SPECS) + [n for n in custom if n not in (event_types or [])]
    unknown = [t for t in types if t not in specs]
    if unknown:
        raise ValueError(f"unknown event types: {unknown}")
    start_ts = pd.Timestamp(start)
    window = flags.index >= start_ts
    labels = state.copy()
    if regimes is not None:
        labels = labels.join(regimes[["market_trend", "volatility"]], how="left")
    baseline = all_day_forward_returns(ind["close"], calendar, p.horizons)
    baseline = baseline[baseline.index >= start_ts]

    studies: list[EventTypeStudy] = []
    warnings: list[WarningItem] = []
    record_parts: list[pd.DataFrame] = []
    for name in types:
        direction, family = specs[name]
        dates = flags.index[window & flags[name].to_numpy(dtype=bool)]
        out = event_outcomes(
            dates,
            ind["close"],
            calendar,
            p.horizons,
            direction=direction,
            high=ind["high"],
            low=ind["low"],
            benchmark=benchmark,
            peers=peers,
            event_type=name,
            ticker=ticker,
        )
        hstats, w = summarize_outcomes(out, direction=direction, params=p, baseline=baseline, label=name)
        warnings.extend(w)
        breakdowns: dict[str, dict[str, list[HorizonStats]]] = {}
        for col in BREAKDOWN_COLUMNS:
            if col not in labels.columns:
                continue
            groups: dict[str, list[HorizonStats]] = {}
            lab = labels[col]
            for value in sorted(lab.loc[dates].dropna().unique()):
                keep = set(dates[(lab.loc[dates] == value).to_numpy()])
                sub = Outcomes(table=out.table[out.table["event_date"].isin(keep)])
                groups[str(value)], _ = summarize_outcomes(sub, direction=direction, params=p)
            breakdowns[col] = groups
        studies.append(
            EventTypeStudy(
                event_type=name,
                family=family,
                direction=direction,
                n_events=len(dates),
                event_dates=tuple(d.date() for d in dates),
                horizons=hstats,
                breakdowns=breakdowns,
                excluded=out.excluded,
            )
        )
        if len(dates):
            rec = labels.loc[dates].copy()
            rec.insert(0, "event_date", dates)
            rec.insert(0, "event_type", name)
            rec["direction"] = direction.value
            fwd = out.table.pivot_table(index="event_date", columns="horizon", values="ret", aggfunc="first")
            for h in p.horizons:
                rec[f"fwd_{h}d"] = rec["event_date"].map(fwd[h]) if h in fwd.columns else float("nan")
            record_parts.append(rec.reset_index(drop=True))

    # multiple testing across the tested family at the main horizon
    raw = [_main(s, main_horizon).p_mean_vs_baseline for s in studies]
    bonf, bh = stats.bonferroni(raw), stats.benjamini_hochberg(raw)
    studies = [
        EventTypeStudy(**{**s.__dict__, "p_bonferroni": b, "p_bh": q})
        for s, b, q in zip(studies, bonf, bh, strict=True)
    ]
    if len(types) > 1:
        warnings.append(
            WarningItem(
                code=WarningCode.MULTIPLE_TESTING_RISK,
                severity=Severity.INFO,
                detail=f"{len(types)} event types tested at h={main_horizon}; Bonferroni/BH adjusted p-values reported",
            )
        )
    records = (
        pd.concat(record_parts, ignore_index=True).sort_values(["event_date", "event_type"], kind="stable")
        if record_parts
        else pd.DataFrame()
    )
    return ReversalStudy(
        ticker=ticker,
        start=start,
        as_of=calendar.as_of,
        main_horizon=main_horizon,
        family_size=len(types),
        studies=studies,
        records=records.reset_index(drop=True),
        warnings=warnings,
    )


def _main(s: EventTypeStudy, h: int) -> HorizonStats:
    return next(x for x in s.horizons if x.horizon == h)
