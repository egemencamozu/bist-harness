"""Parity with the instructor's Scenario 3 script on identical (synthetic) input, plus the documented differences."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from bistharness.analytics import events, indicators
from bistharness.analytics.forward_returns import (
    StudyParams,
    all_day_forward_returns,
    event_outcomes,
    summarize_outcomes,
)
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import Direction
from tests.fixtures.synthetic_market import synthetic_ohlcv
from tests.instructor_reference import S3, load_reference, to_reference_frame

DF = synthetic_ohlcv(600, seed=42)
REF = load_reference(S3)
OURS = indicators.compute_indicators(DF)


def _ref_pipeline(df: pd.DataFrame, ns: dict) -> pd.DataFrame:
    r = to_reference_frame(df)
    for fn in ("add_bollinger_bands", "add_rsi", "add_kama", "add_supertrend", "add_ichimoku", "add_volume_features"):
        r = ns[fn](r)
    r = ns["add_forward_returns"](r, forward_days=5)
    return ns["detect_reversal_events"](r)


REF_OUT = _ref_pipeline(DF, REF)


@pytest.mark.parametrize(
    ("ours", "theirs"),
    [
        ("bb_mid", "BB_Middle"),
        ("bb_upper", "BB_Upper"),
        ("bb_lower", "BB_Lower"),
        ("rsi", "RSI"),
        ("kama", "KAMA"),
        ("kama_slope", "KAMA_Slope"),
        ("atr", "ATR"),
        ("tenkan", "Tenkan"),
        ("kijun", "Kijun"),
        ("senkou_a", "Senkou_A"),
        ("senkou_b", "Senkou_B"),
        ("cloud_top", "Cloud_Top"),
        ("cloud_bottom", "Cloud_Bottom"),
        ("volume_ma", "Volume_MA"),
    ],
)
def test_indicator_values_equal_reference(ours: str, theirs: str) -> None:
    pd.testing.assert_series_equal(OURS[ours], REF_OUT[theirs], check_names=False, rtol=1e-12, atol=0)


def test_volume_rise_equals_reference() -> None:
    assert (OURS["volume_rise"] == REF_OUT["Volume_Rise"]).all()


def test_reference_supertrend_never_initialises() -> None:
    """Documented reference bug: final bands seeded with NaN ATR stay NaN -> no Supertrend value, no flip ever."""
    assert REF_OUT["Supertrend"].isna().all()
    assert not REF_OUT["Supertrend_Bullish_Flip"].any()
    assert OURS["supertrend"].notna().sum() > 500
    assert events.detect_events(OURS)["SUPERTREND_BULLISH_FLIP"].sum() > 0


def _reference_supertrend_from_first_valid_atr(df: pd.DataFrame) -> pd.DataFrame:
    """Run the reference recursion starting on the first bar with a valid ATR (ATR from the full series)."""
    full_atr = REF["add_atr"](to_reference_frame(df))["ATR"]
    s0 = int(np.flatnonzero(full_atr.notna().to_numpy())[0])
    ns = load_reference(S3, add_atr=lambda d, period=10: d.assign(ATR=full_atr.loc[d.index]))
    return ns["add_supertrend"](to_reference_frame(df).iloc[s0:])


def test_supertrend_equals_reference_recursion_after_seeding() -> None:
    ref = _reference_supertrend_from_first_valid_atr(DF)
    ours = OURS.loc[ref.index]
    pd.testing.assert_series_equal(ours["supertrend"], ref["Supertrend"], check_names=False, rtol=1e-12, atol=0)
    pd.testing.assert_series_equal(ours["supertrend_dir"], ref["Supertrend_Direction"], check_names=False)


def test_reference_events_equal_on_identical_input() -> None:
    flags = events.detect_events(OURS)
    for ours, theirs in [
        ("BB_LOWER_REVERSAL", "Bollinger_Reversal"),
        ("RSI_LOCAL_TROUGH", "RSI_Local_Trough"),
        ("RSI_TROUGH_VOLUME", "RSI_Trough_Volume"),
        ("KAMA_BULLISH_TURN", "KAMA_Bullish_Turn"),
        ("ICHIMOKU_BULLISH_BREAKOUT", "Ichimoku_Bullish_Breakout"),
    ]:
        assert (flags[ours] == REF_OUT[theirs].fillna(False).astype(bool)).all(), ours
    # combined events match the reference once its Supertrend is seeded correctly
    st = _reference_supertrend_from_first_valid_atr(DF)
    flip = st["Supertrend_Bullish_Flip"].reindex(DF.index, fill_value=False)
    trend = flip | REF_OUT["Ichimoku_Bullish_Breakout"] | REF_OUT["KAMA_Bullish_Turn"]
    strong = REF_OUT["Bollinger_Reversal"] & REF_OUT["RSI_Local_Trough"] & REF_OUT["Volume_Rise"] & trend
    assert (flags["SUPERTREND_BULLISH_FLIP"] == flip).all()
    assert (flags["TREND_REVERSAL_EVENT"] == trend).all()
    assert (flags["STRONG_REVERSAL_EVENT"] == strong).all()


def test_event_summary_parity_and_explicit_exclusions() -> None:
    """Reference event_summary == our statistics on complete windows; the events the reference drops with
    dropna are exactly our excluded_incomplete_events."""
    cal = TradingCalendar((d.date() for d in DF.index), as_of=DF.index[-1].date())
    fwd = all_day_forward_returns(DF["close"], cal, [5])[5]
    assert (fwd.index == REF_OUT.index).all()
    np.testing.assert_allclose(fwd.to_numpy(), REF_OUT["Forward_5D_Return"].to_numpy(), rtol=1e-12, equal_nan=True)
    flags = events.detect_events(OURS)
    for ours, theirs in [("BB_LOWER_REVERSAL", "Bollinger_Reversal"), ("KAMA_BULLISH_TURN", "KAMA_Bullish_Turn")]:
        summary = REF["event_summary"](REF_OUT, theirs, "Forward_5D_Return", threshold=0.0)
        dates = flags.index[flags[ours]]
        out = event_outcomes(dates, DF["close"], cal, [5], direction=Direction.BULLISH)
        (h5,), _ = summarize_outcomes(out, direction=Direction.BULLISH, params=StudyParams(horizons=(5,)))
        assert h5.n == summary["Event_Count"]
        assert h5.n_success == summary["Successful_Events"]
        assert h5.mean == pytest.approx(summary["Average_Forward_Return_%"] / 100, rel=1e-12)
        assert h5.median == pytest.approx(summary["Median_Forward_Return_%"] / 100, rel=1e-12)
        dropped = sorted(d.date() for d in dates if pd.isna(REF_OUT.at[d, "Forward_5D_Return"]))
        assert sorted(e.event_date for e in out.excluded) == dropped


def test_chikou_is_never_computed() -> None:
    assert not any("chikou" in c.lower() for c in OURS.columns)


def test_defaults_are_the_reference_parameters() -> None:
    p = indicators.IndicatorParams()
    assert (p.bb_window, p.bb_std, p.rsi_period) == (20, 2.0, 14)
    assert (p.kama_er_period, p.kama_fast, p.kama_slow, p.atr_period) == (10, 2, 30, 10)
    assert (p.supertrend_period, p.supertrend_multiplier, p.volume_window) == (10, 3.0, 20)
    assert (p.ichimoku_tenkan, p.ichimoku_kijun, p.ichimoku_senkou_b, p.ichimoku_shift) == (9, 26, 52, 26)
    assert events.EventParams().rsi_trough_max == 40.0
    assert StudyParams().success_threshold == 0.0
    assert date(2024, 1, 1) > DF.index[0].date()  # fixture spans the warm-up
