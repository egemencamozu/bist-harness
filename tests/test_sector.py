"""Scenario 1: lag score, ranks, laggard entries and the catch-up study (synthetic data)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from bistharness.analytics import sector
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import WarningCode
from tests.fixtures.synthetic_market import synthetic_closes

DAYS = pd.bdate_range("2026-06-01", periods=60)
CAL = TradingCalendar((d.date() for d in DAYS), as_of=DAYS[-1].date())
P = sector.SectorParams(windows=(20,), lag_window=20, lag_threshold=-0.05, structural_windows=(30,), horizons=(5, 10))


def _group() -> pd.DataFrame:
    """Three leaders rise 0.8%/day; LAG rises 0.2%/day until day 39, then catches up at 2%/day."""
    n = len(DAYS)
    lead = 100 * 1.008 ** np.arange(n)
    lag_moves = np.where(np.arange(n) < 40, 1.002, 1.02)
    lag_moves[0] = 1.0
    return pd.DataFrame({"A": lead, "B": lead * 1.01, "C": lead * 0.99, "LAG": 100 * np.cumprod(lag_moves)}, index=DAYS)


def test_snapshot_lag_score_uses_leave_one_out_median() -> None:
    cl = _group().iloc[:40]
    cal = TradingCalendar((d.date() for d in DAYS[:40]), as_of=DAYS[39].date())
    snap = sector.sector_snapshot(cl, group="G", calendar=cal, params=P)
    rows = {m.ticker: m for m in snap.rows if m.window == 20}
    r = cl.iloc[-1] / cl.iloc[-21] - 1
    assert rows["LAG"].ret == pytest.approx(r["LAG"])
    assert rows["LAG"].peer_median == pytest.approx(np.median([r["A"], r["B"], r["C"]]))
    assert rows["LAG"].lag_score == pytest.approx(r["LAG"] - np.median([r["A"], r["B"], r["C"]]))
    assert rows["LAG"].rank == 4
    assert snap.laggards == ["LAG"] and snap.persistent_laggards == ["LAG"]
    assert snap.strong[20] is True


def test_weak_sector_has_no_laggards_and_small_group_warns() -> None:
    falling = _group().iloc[:40].iloc[::-1].set_axis(DAYS[:40])  # reversed path = falling sector
    cal = TradingCalendar((d.date() for d in DAYS[:40]), as_of=DAYS[39].date())
    snap = sector.sector_snapshot(falling, group="G", calendar=cal, params=P)
    assert snap.strong[20] is False and snap.laggards == []
    small = sector.sector_snapshot(falling[["A", "B"]], group="G2", calendar=cal, params=P)
    assert [w.code for w in small.warnings] == [WarningCode.SMALL_SECTOR_GROUP]


def test_benchmark_makes_a_sector_weak_when_it_lags_the_market() -> None:
    cl = _group().iloc[:40]
    cal = TradingCalendar((d.date() for d in DAYS[:40]), as_of=DAYS[39].date())
    market = pd.Series(100 * 1.02 ** np.arange(40), index=DAYS[:40])
    snap = sector.sector_snapshot(cl, group="G", calendar=cal, benchmark=market, params=P)
    assert snap.strong[20] is False and snap.laggards == []


def test_laggard_entry_and_catch_up_outcome() -> None:
    cl = _group()
    state = sector.laggard_state(cl, CAL, None, P)
    entries = sector.entry_events(state)
    assert len(entries["LAG"]) == 1 and entries["A"] == []
    study = sector.catch_up_study({"G": cl}, CAL, start=DAYS[0].date(), params=P, main_horizon=10)
    assert study.n_events == 1
    ev = study.events.iloc[0]
    d = ev["event_date"]
    i = DAYS.get_loc(d)
    fwd = cl.iloc[i + 10] / cl.iloc[i] - 1
    assert ev["rel_10d"] == pytest.approx(fwd["LAG"] - fwd[["A", "B", "C"]].mean())
    h10 = next(h for h in study.horizons if h.horizon == 10)
    assert h10.n == 1 and h10.baseline_n > 0
    assert (ev["rel_10d"] > 0) == (h10.n_catch_up == 1)
    assert len(study.false_positives) == (0 if ev["rel_10d"] > 0 else 1)


def test_catch_up_events_near_as_of_are_excluded_not_dropped() -> None:
    cl = _group()
    cut = DAYS.get_loc(sector.entry_events(sector.laggard_state(cl, CAL, None, P))["LAG"][0]) + 7
    cal = TradingCalendar((d.date() for d in DAYS[: cut + 1]), as_of=DAYS[cut].date())
    study = sector.catch_up_study({"G": cl.iloc[: cut + 1]}, cal, start=DAYS[0].date(), params=P)
    assert [(e.ticker, e.horizon, e.trading_days_available) for e in study.excluded] == [("LAG", 10, 7)]
    assert study.n_events == 1


def test_future_rows_do_not_change_the_snapshot() -> None:
    cl = synthetic_closes(["A", "B", "C", "D"], n=120)
    as_of = cl.index[99].date()
    cal = TradingCalendar((d.date() for d in cl.index), as_of=as_of)
    a = sector.sector_snapshot(cl.iloc[:100], group="G", calendar=cal)
    poisoned = cl.copy()
    poisoned.iloc[100:] = 1e6
    b = sector.sector_snapshot(poisoned, group="G", calendar=cal)
    assert a.rows == b.rows and a.laggards == b.laggards and b.as_of == date.fromisoformat(str(as_of))
