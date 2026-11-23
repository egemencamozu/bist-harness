"""Look-ahead (prefix invariance), confirmation dating and event-family properties (synthetic data)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bistharness.analytics import events, indicators, support_resistance
from tests.fixtures.synthetic_market import synthetic_ohlcv

DF = synthetic_ohlcv(450, seed=3)
FULL = indicators.compute_indicators(DF)
FLAGS = events.detect_events(FULL)
STATE = events.market_state(FULL)
CUTS = [120, 200, 287, 333, 449]


@pytest.mark.parametrize("cut", CUTS)
def test_indicators_events_and_state_use_no_future_bars(cut: int) -> None:
    """Values at bar t computed from bars <= t equal the values computed from the full series (no look-ahead)."""
    part = indicators.compute_indicators(DF.iloc[: cut + 1])
    pd.testing.assert_frame_equal(part, FULL.iloc[: cut + 1], check_freq=False)
    pd.testing.assert_frame_equal(events.detect_events(part), FLAGS.iloc[: cut + 1], check_freq=False)
    pd.testing.assert_frame_equal(events.market_state(part), STATE.iloc[: cut + 1], check_freq=False)


def test_poisoned_future_bars_do_not_change_the_past() -> None:
    poisoned = DF.copy()
    poisoned.iloc[300:, poisoned.columns.get_loc("close")] *= 50.0
    poisoned.iloc[300:, poisoned.columns.get_loc("high")] *= 50.0
    ind = indicators.compute_indicators(poisoned)
    pd.testing.assert_frame_equal(ind.iloc[:300], FULL.iloc[:300], check_freq=False)
    pd.testing.assert_frame_equal(events.detect_events(ind).iloc[:300], FLAGS.iloc[:300], check_freq=False)


def test_rsi_trough_is_dated_on_confirmation_day() -> None:
    rsi = FULL["rsi"]
    for t in FLAGS.index[FLAGS["RSI_LOCAL_TROUGH"]][:10]:
        i = FULL.index.get_loc(t)
        assert rsi.iloc[i - 1] < rsi.iloc[i - 2] and rsi.iloc[i - 1] < rsi.iloc[i] and rsi.iloc[i - 1] < 40


def test_kama_price_cross_is_identical_to_kama_slope_turn() -> None:
    """Why KAMA-price crosses are not a separate event family (events.py docstring)."""
    c, k, s = FULL["close"], FULL["kama"], FULL["kama_slope"]
    ok = k.notna() & s.notna() & (s != 0)
    assert ((c > k)[ok] == (s > 0)[ok]).all()
    cross_up = (c.shift(1) <= k.shift(1)) & (c > k)
    assert (
        cross_up[ok & ok.shift(1, fill_value=False)] == FLAGS["KAMA_BULLISH_TURN"][ok & ok.shift(1, fill_value=False)]
    ).all()
    assert "KAMA_PRICE_CROSS_UP" not in events.EVENT_SPECS


def test_every_family_fires_on_synthetic_data_and_specs_are_consistent() -> None:
    assert list(FLAGS.columns) == list(events.EVENT_SPECS)
    fired = {name for name in FLAGS.columns if FLAGS[name].any()}
    families = {events.EVENT_SPECS[n].family for n in fired}
    assert {"bollinger", "rsi", "supertrend", "kama", "ichimoku", "support_resistance"} <= families
    assert set(events.REFERENCE_EVENTS) == {
        "BB_LOWER_REVERSAL",
        "RSI_LOCAL_TROUGH",
        "RSI_TROUGH_VOLUME",
        "KAMA_BULLISH_TURN",
        "SUPERTREND_BULLISH_FLIP",
        "ICHIMOKU_BULLISH_BREAKOUT",
        "TREND_REVERSAL_EVENT",
        "STRONG_REVERSAL_EVENT",
    }


def test_kama_run_counts_consecutive_slope_signs() -> None:
    s = pd.Series([np.nan, 1.0, 2.0, -1.0, -3.0, -0.5, 0.0, 4.0])
    assert events.kama_run(s).tolist()[1:] == [1.0, 2.0, -1.0, -2.0, -3.0, 0.0, 1.0]


def test_event_records_carry_state_and_direction() -> None:
    rec = events.event_records(FLAGS, STATE, ticker="SYN")
    assert len(rec) == int(FLAGS.to_numpy().sum())
    row = rec[rec["event_type"] == "SUPERTREND_BULLISH_FLIP"].iloc[0]
    assert row["direction"] == "bullish" and row["supertrend_state"] == "bullish"
    assert set(rec["ichimoku_state"].dropna()) <= {"above_cloud", "inside_cloud", "below_cloud"}


def test_support_resistance_pivots_are_confirmed_k_bars_later() -> None:
    piv = support_resistance.find_pivots(FULL, k=5)
    assert piv and all(p.confirmed_pos == p.pos + 5 for p in piv)
    for p in piv[:20]:
        window = (
            FULL["high"].iloc[p.pos - 5 : p.pos + 6] if p.kind == "high" else FULL["low"].iloc[p.pos - 5 : p.pos + 6]
        )
        assert p.price == (window.max() if p.kind == "high" else window.min())


def test_support_resistance_snapshot_sides_and_zones() -> None:
    params = support_resistance.SRParams()
    levels = support_resistance.find_support_resistance(FULL, params)
    close = FULL["close"].iloc[-1]
    assert levels
    for lv in levels:
        assert lv.touches >= params.min_touches and lv.zone_low <= lv.price <= lv.zone_high
        assert (lv.zone_high - lv.zone_low) / lv.zone_low <= params.tolerance + 1e-12
        assert lv.side != "support" or lv.zone_high < close
        assert lv.side != "resistance" or lv.zone_low > close
        assert lv.known_from <= FULL.index[-1]


def test_touch_events_only_use_levels_known_the_day_before() -> None:
    full = support_resistance.touch_events(FULL)
    part = support_resistance.touch_events(FULL.iloc[:301])
    pd.testing.assert_frame_equal(part, full.iloc[:301], check_freq=False)
