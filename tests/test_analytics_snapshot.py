"""Analytics on the real frozen snapshot at the golden as_of (skipped when the DB is missing).

Pins the golden-question facts the harness will rely on (CLAUDE.md §10) so a code or data change cannot silently
move them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date

import pandas as pd
import pytest

from bistharness.analytics import event_study, events, indicators, macro_stats, regimes, sector, series, weekday
from bistharness.analytics import fundamentals as fa
from bistharness.core.calendar import TradingCalendar
from bistharness.core.config import load_settings, load_universe
from bistharness.core.pit import PITRepository
from tests.instructor_reference import S3, load_reference, to_reference_frame

DB = load_settings().db_path
pytestmark = [pytest.mark.data, pytest.mark.skipif(not DB.exists(), reason="snapshot DB not built")]
AS_OF = date(2026, 9, 10)
TICKERS = ["ASELS", "XU100", "TUPRS", "THYAO", "BIMAS", "MGROS", "MAVI", "SOKM", "EREGL"]


@pytest.fixture(scope="module")
def repo() -> Iterator[PITRepository]:
    conn = sqlite3.connect(f"{DB.resolve().as_uri()}?mode=ro", uri=True)
    yield PITRepository(conn)
    conn.close()


@pytest.fixture(scope="module")
def px(repo: PITRepository) -> pd.DataFrame:
    return repo.prices(TICKERS, "2023-01-01", as_of=AS_OF).data


@pytest.fixture(scope="module")
def cal(repo: PITRepository) -> TradingCalendar:
    return repo.trading_calendar(as_of=AS_OF)


def test_asels_reference_events_and_the_supertrend_bug_on_real_data(px: pd.DataFrame, cal: TradingCalendar) -> None:
    a = series.ohlcv(px, "ASELS")
    ours = indicators.compute_indicators(a)
    flags = events.detect_events(ours)
    ns = load_reference(S3)
    ref = to_reference_frame(a)
    for fn in ("add_bollinger_bands", "add_rsi", "add_kama", "add_supertrend", "add_ichimoku", "add_volume_features"):
        ref = ns[fn](ref)
    ref = ns["detect_reversal_events"](ref)
    assert (flags["BB_LOWER_REVERSAL"] == ref["Bollinger_Reversal"]).all()
    assert (flags["RSI_LOCAL_TROUGH"] == ref["RSI_Local_Trough"]).all()
    assert ref["Supertrend_Bullish_Flip"].sum() == 0  # the reference never initialises Supertrend
    assert flags["SUPERTREND_BULLISH_FLIP"].sum() > 10

    xu = series.ohlcv(px, "XU100")["close"]
    study = event_study.reversal_event_study(
        ours,
        flags,
        events.market_state(ours),
        cal,
        ticker="ASELS",
        start=date(2024, 1, 1),
        benchmark=xu,
        regimes=regimes.market_regimes(xu),
    )
    bb = study.study("BB_LOWER_REVERSAL")
    h5 = next(h for h in bb.horizons if h.horizon == 5)
    assert bb.n_events == h5.n + sum(1 for e in bb.excluded if e.horizon == 5)
    assert study.family_size == len(events.EVENT_SPECS) and all(s.p_bh is None or s.p_bh <= 1 for s in study.studies)
    assert set(bb.breakdowns["market_trend"]) <= {"rising", "falling"}


def test_tuprs_2026q2_fundamentals_and_reaction(repo: PITRepository, px: pd.DataFrame, cal: TradingCalendar) -> None:
    inst = load_universe().instrument("TUPRS")
    reps = fa.build_reports(repo.fundamentals("TUPRS", as_of=AS_OF, role=None, latest_only=False).data, ticker="TUPRS")
    rep = reps["2026Q2"]
    assert rep.disclosure_datetime == "2026-08-04 18:24:32"
    rm = fa.report_metrics(rep, reps, template=inst.template, tms29_applies=inst.tms29_applies)
    assert rm.levels["revenue"]["yoy_ytd"].value == pytest.approx(662_788_010_000 / 464_119_398_000 - 1)
    assert rm.levels["revenue"]["yoy_ytd"].sources == (rep.disclosure_index,)
    raw = px[px["ticker"] == "TUPRS"].set_index("date")["raw_close"]
    val = fa.valuation(
        rm, reps, day=AS_OF, raw_close=float(raw.iloc[-1]), actions=repo.corporate_actions("TUPRS", as_of=AS_OF)
    )
    assert val.shares == 1_926_796_000 and val.metrics["pe"].value == pytest.approx(11.896, abs=1e-3)
    reac = fa.post_disclosure_reactions(
        [rep], series.ohlcv(px, "TUPRS")["close"], cal, benchmark=series.ohlcv(px, "XU100")["close"]
    )
    assert reac.excluded == []  # 27 trading days after 2026-08-04: the 20-day window is complete (golden Q4)
    assert set(reac.table["timing"]) == {"after_close"} and set(reac.table["event_date"]) == {
        pd.Timestamp("2026-08-04")
    }


def test_retail_golden_windows(repo: PITRepository, px: pd.DataFrame, cal: TradingCalendar) -> None:
    bimas = fa.build_reports(repo.fundamentals("BIMAS", as_of=AS_OF, role=None, latest_only=False).data, ticker="BIMAS")
    reac = fa.post_disclosure_reactions([bimas["2026Q2"]], series.ohlcv(px, "BIMAS")["close"], cal)
    assert [(e.event_date, e.horizon, e.trading_days_available) for e in reac.excluded] == [(date(2026, 8, 17), 20, 18)]
    mavi = fa.build_reports(repo.fundamentals("MAVI", as_of=AS_OF, role=None, latest_only=False).data, ticker="MAVI")
    assert max(mavi) == "2026Q1"  # MAVI 2026Q2 is published on 2026-09-16, after the golden as_of
    snap = sector.sector_snapshot(
        series.column_matrix(px, ["BIMAS", "MGROS", "MAVI", "SOKM"]),
        group="Perakende",
        calendar=cal,
        benchmark=series.ohlcv(px, "XU100")["close"],
    )
    assert snap.members_with_data == ("BIMAS", "MGROS", "MAVI", "SOKM") and snap.warnings == []


def test_thyao_weekday_pattern_in_and_out_of_sample(px: pd.DataFrame) -> None:
    ret = weekday.daily_returns(series.ohlcv(px, "THYAO")["close"])
    pat = weekday.WeekdayPattern(
        (("Mon", -1), ("Tue", -1), ("Wed", -1)), ("Thu", "Fri"), descriptive_outcome_signs=(("Thu", 1), ("Fri", 1))
    )
    res = weekday.evaluate_weekday_pattern(
        ret,
        pat,
        periods={"in_sample": (date(2024, 1, 1), date(2025, 12, 31)), "out_of_sample": (date(2026, 1, 1), AS_OF)},
        as_of=AS_OF,
    )
    is_, oos = res.periods
    assert (is_.complete_weeks, is_.condition_weeks) == (87, 19)
    assert (oos.complete_weeks, oos.condition_weeks) == (29, 3)
    assert oos.family_size == 8 and any(w.code.value == "INSUFFICIENT_SAMPLE" for w in oos.warnings)


def test_macro_context_and_eregl_fx_relationship(repo: PITRepository, px: pd.DataFrame) -> None:
    codes = ["USDTRY", "EURTRY", "TCMB_POLICY_RATE", "FED_TARGET_UPPER", "FED_TARGET_LOWER", "TUFE_YOY", "TUFE_MOM"]
    m = repo.macro(codes, as_of=AS_OF).data
    snap = macro_stats.macro_snapshot(m, AS_OF)
    assert snap.latest["TCMB_POLICY_RATE"].value == 37.0 and snap.latest["TUFE_YOY"].value == 31.51
    assert snap.real_policy_rate == pytest.approx(37.0 - 31.51) and snap.warnings == []
    fx = m[m["series_code"] == "USDTRY"].assign(d=lambda d: pd.to_datetime(d["obs_date"])).set_index("d")["value"]
    rel = macro_stats.fx_relationship(series.ohlcv(px, "EREGL")["close"], fx, start=date(2024, 1, 1))
    assert rel.correlation.n == 140 and rel.end == AS_OF  # last real observation, not the Friday bin label
