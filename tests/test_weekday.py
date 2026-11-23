"""Scenario 2: parity with the instructor's script, condition != outcome, periods, exclusions (synthetic data)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from bistharness.analytics import weekday
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import WarningCode
from tests.fixtures.synthetic_market import synthetic_ohlcv
from tests.instructor_reference import S2, load_reference

REF = load_reference(S2)
CLOSE = synthetic_ohlcv(600, seed=11)["close"]
RET = weekday.daily_returns(CLOSE)
THYAO_LIKE = weekday.WeekdayPattern(
    (("Mon", -1), ("Tue", -1), ("Wed", -1)), ("Thu", "Fri"), descriptive_outcome_signs=(("Thu", 1), ("Fri", 1))
)


def _reference_frame(close: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"Close": close})
    df["Return"] = df["Close"].pct_change()
    df["WeekdayNum"] = df.index.day_of_week
    df["Weekday"] = df["WeekdayNum"].map({0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"})
    iso = df.index.isocalendar()
    df["ISO_Year"] = iso.year.astype(int)
    df["ISO_Week"] = iso.week.astype(int)
    return df.dropna(subset=["Return"])


REF_DF = _reference_frame(CLOSE)
REF_WEEKLY = REF["detect_pattern"](REF["build_weekly_pattern_table"](REF_DF))


def test_weekday_statistics_equal_reference() -> None:
    ours = weekday.weekday_statistics(RET)
    ref = REF["weekday_statistics"](REF_DF)
    assert (ours["n"] == ref["Observations"]).all()
    for o, r in [
        ("mean", "Average_Return"),
        ("median", "Median_Return"),
        ("std", "Std_Dev"),
        ("positive_rate", "Positive_Rate"),
    ]:
        np.testing.assert_allclose(ours[o].to_numpy(dtype=float) * 100, ref[r].to_numpy(dtype=float), rtol=1e-12)


def test_weekly_table_equals_reference() -> None:
    ours = weekday.weekly_table(RET).set_index(["iso_year", "iso_week"])[list(weekday.DAYS)]
    ref = REF_WEEKLY.set_index(["ISO_Year", "ISO_Week"])[list(weekday.DAYS)]
    np.testing.assert_allclose(ours.to_numpy(dtype=float), ref.to_numpy(dtype=float), rtol=1e-12, equal_nan=True)


def test_reference_pattern_counts_are_our_descriptive_full_sequence() -> None:
    summary = REF["pattern_summary"](REF_WEEKLY, transaction_cost=0.001)
    as_of = CLOSE.index[-1].date()
    res = weekday.evaluate_weekday_pattern(
        RET, THYAO_LIKE, periods={"full": (CLOSE.index[0].date(), as_of)}, as_of=as_of
    ).periods[0]
    assert res.complete_weeks == summary["Complete weeks"]
    assert res.full_sequence_count == summary["Pattern occurrences"]
    assert res.full_sequence_frequency * 100 == pytest.approx(summary["Pattern frequency (%)"])
    # the reference conditions on Thu>0 & Fri>0, so its "positive Thu-Fri rate" is 100% by construction
    assert summary["Positive Thu-Fri rate (%)"] == 100.0
    # ours conditions on Mon-Wed only: the outcome can be negative
    assert res.condition_weeks >= res.full_sequence_count
    assert res.conditional.positive_rate is not None and res.conditional.positive_rate < 1.0


def test_condition_must_not_contain_the_outcome() -> None:
    with pytest.raises(ValueError, match="outcome days must come after"):
        weekday.WeekdayPattern((("Mon", -1), ("Thu", 1)), ("Thu", "Fri"))
    with pytest.raises(ValueError, match="outcome days must come after"):
        weekday.WeekdayPattern((("Wed", -1),), ("Tue",))


def test_family_adjustment_and_unconditional_comparison() -> None:
    as_of = CLOSE.index[-1].date()
    res = weekday.evaluate_weekday_pattern(RET, THYAO_LIKE, periods={"full": (date(2023, 1, 1), as_of)}, as_of=as_of)
    p = res.periods[0]
    assert p.family_size == 8
    assert p.p_bonferroni is not None and p.p_welch_vs_complement is not None
    assert p.p_bonferroni >= p.p_welch_vs_complement
    assert p.conditional.n + p.complement.n == p.unconditional.n == p.complete_weeks
    assert p.mean_difference == pytest.approx(p.conditional.mean - p.unconditional.mean)
    assert p.conditional.mean_after_cost == pytest.approx(p.conditional.mean - 0.001)
    assert any(w.code == WarningCode.MULTIPLE_TESTING_RISK for w in p.warnings)


def test_periods_assign_whole_weeks_and_holiday_weeks_are_incomplete() -> None:
    gappy = RET.drop(pd.Timestamp("2023-03-15"))  # a Wednesday -> that week is incomplete
    as_of = CLOSE.index[-1].date()
    split = date(2024, 1, 3)  # mid-week: the week of 2024-01-01 belongs to neither period
    res = weekday.evaluate_weekday_pattern(
        gappy,
        THYAO_LIKE,
        periods={"is": (date(2023, 1, 1), date(2024, 1, 2)), "oos": (split, as_of)},
        as_of=as_of,
    )
    total = weekday.weekly_table(gappy)
    week_2024_01 = (total["iso_year"] == 2024) & (total["iso_week"] == 1)
    assert week_2024_01.sum() == 1
    assert sum(p.complete_weeks for p in res.periods) == int(total["complete"].sum()) - 1
    assert res.periods[0].incomplete_weeks >= 2  # first week (no Monday return) + the holiday week


def test_mid_week_as_of_reports_the_incomplete_outcome() -> None:
    days = pd.bdate_range("2026-07-31", "2026-09-10")  # Friday start -> first return on Monday; as_of = Thursday
    moves = np.where(days.day_of_week < 3, -0.01, 0.01)
    moves[0] = 0.0
    close = pd.Series(100 * np.cumprod(1 + moves), index=days)
    ret = weekday.daily_returns(close)
    res = weekday.evaluate_weekday_pattern(
        ret, THYAO_LIKE, periods={"oos": (date(2026, 8, 3), date(2026, 9, 10))}, as_of=date(2026, 9, 10)
    )
    (ex,) = res.excluded
    assert ex.event_date == date(2026, 9, 7) and ex.horizon == 2 and ex.trading_days_available == 1
    assert ex.reason == WarningCode.FORWARD_WINDOW_INCOMPLETE
    assert res.periods[0].condition_weeks == 5  # 5 complete weeks before, the current week is not counted


def test_sequence_pattern_events_and_exclusions() -> None:
    days = pd.bdate_range("2026-01-05", periods=40)
    moves = np.array([-0.01, -0.01, -0.01, 0.02, 0.01] * 8)
    close = pd.Series(100 * np.cumprod(1 + moves), index=days)
    cal = TradingCalendar((d.date() for d in days), as_of=days[-1].date())
    res = weekday.evaluate_sequence_pattern(
        close, weekday.SequencePattern("consecutive_down", 3), cal, start=days[0].date()
    )
    assert res.n_events == 7  # every third down day except the first week's (its first return is NaN)
    h1 = next(h for h in res.horizons if h.horizon == 1)
    assert h1.n == 7 and h1.success_rate == 1.0  # the next day is always +2%
    assert all(e.event_date == days[-3].date() for e in res.excluded)  # the last event lacks 3- and 5-day windows
