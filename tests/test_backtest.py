"""Backtest engine timing/costs (hand-computed), metrics, and point-in-time strategy masks (synthetic data)."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from bistharness.backtest import strategies
from bistharness.backtest.engine import CostModel, buy_and_hold_returns, simulate
from bistharness.backtest.metrics import daily_risk_free, max_drawdown, return_metrics, trade_stats
from bistharness.core.enums import FundamentalTemplate
from tests.test_fundamentals_analytics import FLOW, _rows

DAYS = pd.bdate_range("2026-03-02", periods=12)
OPENS = pd.DataFrame({"A": [100.0 + i for i in range(12)], "B": [50.0] * 12}, index=DAYS)
CLOSES = pd.DataFrame({"A": [100.5 + i for i in range(12)], "B": [50.0] * 12}, index=DAYS)


def test_signal_executes_next_open_and_exits_at_open_after_holding_days() -> None:
    res = simulate({"A": [DAYS[1]]}, OPENS, CLOSES, DAYS, holding_days=3, costs=CostModel(10, 5), universe=["A", "B"])
    (t,) = res.trades
    c = 15 / 10_000
    assert (t.entry_date, t.exit_date, t.status) == (DAYS[2], DAYS[5], "closed")
    assert (t.entry_price, t.exit_price) == (102.0, 105.0)
    assert t.net_return == pytest.approx(105 * (1 - c) / (102 * (1 + c)) - 1)
    # compounding the sleeve's daily returns reproduces the trade exactly; the flat sleeve earns 0
    assert float(np.prod(1 + res.sleeve_returns["A"]) - 1) == pytest.approx(t.net_return)
    assert (res.sleeve_returns["B"] == 0).all()
    assert res.portfolio_returns.iloc[3] == pytest.approx(res.sleeve_returns["A"].iloc[3] / 2)
    assert res.exposure.iloc[2] == 0.5 and res.exposure.iloc[5] == 0.0  # exit day: out at the open


def test_overlapping_signal_is_skipped_and_last_day_signal_is_pending() -> None:
    res = simulate(
        {"A": [DAYS[1], DAYS[2], DAYS[11]]}, OPENS, CLOSES, DAYS, holding_days=3, costs=CostModel(0), universe=["A"]
    )
    assert len(res.trades) == 1 and res.skipped_signals == 1
    assert res.pending_signals == [("A", DAYS[11])]


def test_trade_open_at_as_of_is_marked_to_last_close_and_not_a_win() -> None:
    res = simulate({"A": [DAYS[8]]}, OPENS, CLOSES, DAYS, holding_days=5, costs=CostModel(10), universe=["A"])
    (t,) = res.trades
    assert t.status == "open" and t.exit_date is None and t.exit_price == CLOSES["A"].iloc[-1]
    st = trade_stats(res.trades)
    assert (st.n_signals, st.n_closed, st.n_open, st.win_rate) == (1, 0, 1, None)


def test_halted_open_is_not_tradable() -> None:
    opens = OPENS.copy()
    opens.loc[DAYS[2], "A"] = np.nan
    res = simulate({"A": [DAYS[1]]}, opens, CLOSES, DAYS, holding_days=2, costs=CostModel(0), universe=["A"])
    assert res.trades == [] and res.skipped_signals == 1


def test_metrics() -> None:
    r = pd.Series([0.10, -0.20, 0.05, 0.0], index=DAYS[:4])
    m = return_metrics(r)
    assert m.cumulative == pytest.approx(1.1 * 0.8 * 1.05 - 1)
    assert m.max_drawdown == pytest.approx(0.8 - 1)
    assert m.sharpe_rf0 == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(252))
    assert max_drawdown(pd.Series([-0.1, 0.05], index=DAYS[:2])) == pytest.approx(-0.1)
    rf = daily_risk_free(pd.Series([36.0], index=[DAYS[0]]), DAYS[:4])
    assert rf.iloc[-1] == pytest.approx(1.36 ** (1 / 252) - 1)
    assert return_metrics(r, rf).sharpe_policy < m.sharpe_rf0
    bh = buy_and_hold_returns(CLOSES, DAYS)
    assert bh.iloc[0] == 0 and bh.iloc[1] == pytest.approx(((101.5 / 100.5 - 1) + 0) / 2)


def test_fundamental_mask_uses_disclosure_time() -> None:
    rows = pd.DataFrame(
        _rows(
            "2026Q1",
            1,
            "2026-05-05 18:30:00",
            {("2026Q1", "3M"): FLOW(110, 30, 12)},
            {("2025Q1", "3M"): FLOW(100, 25, 10)},
        )
        + _rows(
            "2026Q2",
            2,
            "2026-08-04 18:24:32",
            {("2026Q2", "6M"): FLOW(200, 60, 20)},
            {("2025Q2", "6M"): FLOW(210, 50, 25)},
        )
    )
    tl = strategies.fundamental_timeline(rows, "SYN", FundamentalTemplate.INDUSTRIAL, strategies.StrategySpec())
    assert tl["ok"].tolist() == [True, False]  # Q1 grows; Q2 revenue and profit fall vs the prior year
    days = pd.DatetimeIndex(["2026-05-04", "2026-05-05", "2026-08-03", "2026-08-04", "2026-08-05"])
    mask = strategies.fundamental_mask(tl, days)
    # known at the end of the disclosure day (decision for the next open), never before
    assert mask.tolist() == [False, True, True, False, False]


def test_macro_and_news_masks() -> None:
    days = pd.bdate_range("2026-01-01", periods=40)
    fx = [
        ("USDTRY", d.date().isoformat(), 30.0 * (1.004 if i > 25 else 1.0) ** max(0, i - 25), f"{d.date()} 15:30:00")
        for i, d in enumerate(days)
    ]
    rates = [
        ("TCMB_POLICY_RATE", "2025-12-01", 38.0, "2025-12-01 00:00:00"),
        ("TCMB_POLICY_RATE", "2026-01-20", 40.0, "2026-01-20 00:00:00"),
    ]
    macro = pd.DataFrame(fx + rates, columns=["series_code", "obs_date", "value", "release_datetime"])
    m = strategies.macro_mask(macro, days, strategies.StrategySpec())
    hike_day = days.get_loc(pd.Timestamp("2026-01-20"))
    assert m.iloc[:hike_day].all() and not m.iloc[hike_day : hike_day + 5].any()
    news = pd.DataFrame(
        {
            "published_at": ["2026-01-07 11:00:00", "2026-01-08 09:00:00"],
            "tickers": [json.dumps(["SYN"]), json.dumps(["OTHER"])],
            "topics": [json.dumps(["regulation"]), json.dumps(["regulation"])],
        }
    )
    nm = strategies.news_mask(news, "SYN", days, strategies.StrategySpec())
    blocked = [d.date().isoformat() for d in days[~nm.to_numpy()]]
    assert blocked == ["2026-01-07", "2026-01-08", "2026-01-09"]


def test_spec_rejects_bearish_entries() -> None:
    with pytest.raises(ValueError, match="long only"):
        strategies.StrategySpec(entry_events=("BB_UPPER_TOUCH",))
    with pytest.raises(ValueError, match="unknown variant"):
        strategies.apply_variant(pd.DataFrame(), {}, "Z")
