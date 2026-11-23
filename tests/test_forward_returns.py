"""Forward-window completeness, exclusions, abnormal returns and statistics (synthetic data)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from bistharness.analytics import stats
from bistharness.analytics.forward_returns import (
    StudyParams,
    all_day_forward_returns,
    event_outcomes,
    summarize_outcomes,
)
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import Direction, WarningCode

DAYS = pd.bdate_range("2026-08-03", periods=30)
CLOSE = pd.Series(100.0 * 1.01 ** np.arange(30), index=DAYS)
AS_OF = DAYS[24].date()  # 5 known days remain after DAYS[19]
CAL = TradingCalendar((d.date() for d in DAYS), as_of=AS_OF)


def test_incomplete_windows_are_excluded_with_days_available() -> None:
    out = event_outcomes([DAYS[19], DAYS[22]], CLOSE, CAL, [1, 5, 10], direction=Direction.BULLISH, ticker="SYN")
    got = {(e.event_date, e.horizon): e.trading_days_available for e in out.excluded}
    assert got == {(DAYS[19].date(), 10): 5, (DAYS[22].date(), 5): 2, (DAYS[22].date(), 10): 2}
    assert all(e.reason == WarningCode.FORWARD_WINDOW_INCOMPLETE for e in out.excluded)
    r5 = out.table[(out.table["horizon"] == 5) & (out.table["event_date"] == DAYS[19])]
    assert r5["end_date"].iloc[0] == DAYS[24]
    assert r5["ret"].iloc[0] == pytest.approx(1.01**5 - 1)


def test_future_prices_beyond_as_of_are_ignored() -> None:
    poisoned = CLOSE.copy()
    poisoned.iloc[25:] = 1e9  # after as_of
    a = event_outcomes([DAYS[15]], CLOSE, CAL, [1, 5, 10], direction=Direction.BULLISH)
    b = event_outcomes([DAYS[15]], poisoned, CAL, [1, 5, 10], direction=Direction.BULLISH)
    pd.testing.assert_frame_equal(a.table, b.table)
    assert [e.horizon for e in b.excluded] == [10]


def test_missing_bar_is_excluded_not_dropped() -> None:
    gappy = CLOSE.drop(DAYS[12])
    out = event_outcomes([DAYS[10]], gappy, CAL, [2, 3], direction=Direction.BULLISH)
    assert [(e.horizon, e.reason) for e in out.excluded] == [(2, WarningCode.PRICE_MISSING)]
    assert out.table["horizon"].tolist() == [3]


def test_event_after_as_of_or_off_calendar_raises() -> None:
    with pytest.raises(ValueError, match="after as_of"):
        event_outcomes([DAYS[26]], CLOSE, CAL, [1])
    with pytest.raises(ValueError, match="not a trading day"):
        event_outcomes([date(2026, 8, 8)], CLOSE, CAL, [1])  # Saturday


def test_abnormal_returns_and_reversal_strength() -> None:
    bench = pd.Series(100.0 * 1.005 ** np.arange(30), index=DAYS)
    peers = pd.DataFrame({"P1": 100.0 * 1.002 ** np.arange(30), "P2": 100.0 * 0.998 ** np.arange(30)}, index=DAYS)
    high = CLOSE * 1.03
    out = event_outcomes(
        [DAYS[5]], CLOSE, CAL, [4], direction=Direction.BULLISH, benchmark=bench, peers=peers, high=high
    )
    row = out.table.iloc[0]
    assert row["abn_benchmark"] == pytest.approx(1.01**4 - 1.005**4)
    assert row["abn_peers"] == pytest.approx(1.01**4 - 1 - ((1.002**4 - 1) + (0.998**4 - 1)) / 2)
    assert row["mfe"] == pytest.approx(1.03 * 1.01**4 - 1)


def test_summary_counts_success_baseline_and_overlap() -> None:
    rng = np.random.default_rng(0)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 30))), index=DAYS)
    ev = [DAYS[2], DAYS[3], DAYS[10], DAYS[16]]
    out = event_outcomes(ev, close, CAL, [1, 5], direction=Direction.BEARISH)
    base = all_day_forward_returns(close, CAL, [1, 5])
    (_h1, h5), warns = summarize_outcomes(
        out, direction=Direction.BEARISH, params=StudyParams(horizons=(1, 5)), baseline=base
    )
    r5 = out.table.loc[out.table["horizon"] == 5, "ret"].to_numpy()
    assert h5.n == 4 and h5.n_success == int((r5 < 0).sum())
    assert h5.n_independent == 3  # DAYS[2]/DAYS[3] windows overlap
    assert h5.baseline_n == int(base[5].notna().sum()) - 4
    assert {w.code for w in warns} == {WarningCode.INSUFFICIENT_SAMPLE}


def test_closed_form_tests_equal_scipy() -> None:
    rng = np.random.default_rng(1)
    x, y = rng.normal(0.1, 1, 40), rng.normal(0, 2, 25)
    assert stats.t_test_mean(x).p_value == pytest.approx(sps.ttest_1samp(x, 0).pvalue, rel=1e-10)
    assert stats.welch_t_test(x, y).p_value == pytest.approx(sps.ttest_ind(x, y, equal_var=False).pvalue, rel=1e-10)


def test_multiple_testing_adjustments() -> None:
    p = [0.01, 0.04, None, 0.03, 0.2]
    assert stats.bonferroni(p) == [0.04, 0.16, None, 0.12, 0.8]
    bh = stats.benjamini_hochberg(p)
    assert bh[2] is None
    assert (
        bh[0] == pytest.approx(0.04) and bh[3] == pytest.approx(0.04 * 4 / 3) and bh[1] == pytest.approx(0.04 * 4 / 3)
    )
    assert bh[4] == pytest.approx(0.2)


def test_wilson_bootstrap_and_permutation_are_deterministic() -> None:
    lo, hi = stats.wilson_interval(11, 17) or (0, 0)
    assert lo == pytest.approx(0.4130, abs=1e-4) and hi == pytest.approx(0.8269, abs=1e-4)
    x = [0.01, -0.02, 0.03, 0.04, -0.01]
    assert stats.bootstrap_mean_ci(x, seed=42) == stats.bootstrap_mean_ci(x, seed=42)
    assert stats.permutation_test_mean_diff(x, [0.0, 0.0, 0.01], seed=42) == stats.permutation_test_mean_diff(
        x, [0.0, 0.0, 0.01], seed=42
    )
    assert stats.greedy_non_overlapping([0, 1, 5, 6, 12], 5) == 3
