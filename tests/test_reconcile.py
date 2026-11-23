"""Source reconciliation on synthetic series that reproduce the real defects of the 2026-11-20 snapshot:

* price-scraper (primary): printed prices + bonus factor on the true (ekofin) ex-date, no dividend adjustment;
* yfinance (secondary): adjusts history for the bonus only a few days back, leaving a fake jump (CCOLA-like),
  a truncated bar (2023-01-05-like), a placeholder day, dividends in Adj Close.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bistharness.core.enums import Severity, WarningCode
from bistharness.data.ingest.reconcile import build_trading_calendar, reconcile_ticker, yf_unadjust_splits

KW = {"band": 0.105, "min_log_change": 0.003, "source_disagreement": 0.01}
N = 120
BONUS, YF_WRONG_FROM, DIV = 60, 55, 80


def _world(div_day: int = DIV, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=N)
    total = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, N)))  # total-return path
    printed = total.copy()
    printed[BONUS:] /= 2  # 1:1 bonus, true ex-date BONUS
    printed[div_day:] *= 0.95  # 5 % dividend
    ps_adj_factor = np.where(np.arange(N) < BONUS, 2.0, 1.0)
    ps = pd.DataFrame(
        {
            "open": printed * 0.995,
            "high": printed * 1.01,
            "low": printed * 0.99,
            "close": printed,
            "volume": 5000.0,
            "ps_adj_close": printed / ps_adj_factor,
            "ps_has_adj": True,
        },
        index=idx,
    )
    # yfinance: history adjusted for the bonus only on [YF_WRONG_FROM, BONUS) -> fake -50 % jump on YF_WRONG_FROM
    yf_close = printed * np.where((np.arange(N) >= YF_WRONG_FROM) & (np.arange(N) < BONUS), 0.5, 1.0)
    div_factor = np.where(np.arange(N) < div_day, 0.95, 1.0)
    yf = pd.DataFrame(
        {
            "Open": yf_close * 0.995,
            "High": yf_close * 1.01,
            "Low": yf_close * 0.99,
            "Close": yf_close,
            "Adj Close": yf_close * div_factor,
            "Volume": 1000.0,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=idx,
    )
    yf.loc[idx[div_day], "Dividends"] = 1.0
    return {"idx": idx, "printed": printed, "total": total, "ps": ps, "yf": yf}


def _adj(p: pd.DataFrame) -> pd.Series:
    return p["close"] * p["cum_factor"]


def _ret_equal(p: pd.DataFrame, total: np.ndarray, idx: pd.DatetimeIndex) -> bool:
    ours = _adj(p).pct_change().dropna()
    truth = pd.Series(total, idx).pct_change().reindex(ours.index)
    return bool(np.allclose(ours, truth))


def test_price_scraper_is_primary_and_wrong_dated_yfinance_bonus_is_ignored() -> None:
    w = _world()
    idx = w["idx"]
    res = reconcile_ticker("SYN", w["ps"], w["yf"], pd.DatetimeIndex(idx), **KW)
    p = res.prices
    assert np.allclose(p["close"], w["printed"])  # incl. days 55-59 where yfinance shows half the price
    assert _ret_equal(p, w["total"], idx)
    a = res.actions.set_index("ex_date")
    assert list(a.index) == [idx[BONUS], idx[DIV]]  # nothing on the wrong yfinance date
    assert a.loc[idx[BONUS], "source"] == "price_scraper" and a.loc[idx[BONUS], "ratio"] == pytest.approx(2.0)
    assert a.loc[idx[DIV], "kind"] == "dividend" and a.loc[idx[DIV], "ratio"] == pytest.approx(1 / 0.95)
    wrong = [f for f in res.flags if f.code is WarningCode.SOURCE_DISAGREEMENT and f.date == idx[YF_WRONG_FROM].date()]
    assert wrong and wrong[0].severity is Severity.INFO  # documented, primary was used
    assert (p["price_source"] == "price_scraper").all()


def test_truncated_yfinance_bar_does_not_leak() -> None:
    w = _world()
    idx = w["idx"]
    yf = w["yf"].copy()
    yf.loc[idx[40], ["Close", "Adj Close", "Low"]] *= 1.045
    yf.loc[idx[40], "Volume"] *= 0.3
    res = reconcile_ticker("SYN", w["ps"], yf, pd.DatetimeIndex(idx), **KW)
    p = res.prices
    assert p.loc[idx[40], "close"] == pytest.approx(w["printed"][40])
    assert p.loc[idx[40], "low"] == pytest.approx(w["printed"][40] * 0.99)
    assert p.loc[idx[40], "volume"] == 5000.0
    assert idx[40] not in set(res.actions["ex_date"])


def test_gap_in_price_scraper_is_filled_and_next_day_reanchors() -> None:
    w = _world()
    idx = w["idx"]
    ps = w["ps"].drop(index=idx[30])
    res = reconcile_ticker("SYN", ps, w["yf"], pd.DatetimeIndex(idx), **KW)
    p = res.prices
    assert p.loc[idx[30], "price_source"] == "yfinance"
    assert p.loc[idx[31], "price_source"] == "price_scraper"
    assert np.allclose(p["close"], w["printed"])
    assert _ret_equal(p, w["total"], idx)
    filled = [f for f in res.flags if f.code is WarningCode.FILLED_FROM_SECONDARY]
    assert [f.date for f in filled] == [idx[30].date()] and filled[0].severity is Severity.SOFT


def test_one_day_price_scraper_glitch_falls_back_without_shifting_history() -> None:
    w = _world()
    idx = w["idx"]
    ps = w["ps"].copy()
    ps.loc[idx[45], ["close", "ps_adj_close"]] *= 1.3
    res = reconcile_ticker("SYN", ps, w["yf"], pd.DatetimeIndex(idx), **KW)
    p = res.prices
    assert p.loc[idx[45], "price_source"] == "yfinance"
    assert p.loc[idx[46], "price_source"] == "price_scraper"
    assert np.allclose(p["close"], w["printed"])
    assert not {idx[45], idx[46]} & set(res.actions["ex_date"])


def test_yfinance_placeholder_day_is_irrelevant_when_primary_exists() -> None:
    w = _world()
    idx = w["idx"]
    yf = w["yf"].copy()
    yf.loc[idx[70], ["Open", "High", "Low", "Close", "Adj Close"]] = yf.loc[idx[69], "Close"]
    yf.loc[idx[70], "Volume"] = 0.0
    res = reconcile_ticker("SYN", w["ps"], yf, pd.DatetimeIndex(idx), **KW)
    assert res.prices.loc[idx[70], "close"] == pytest.approx(w["printed"][70])
    assert _ret_equal(res.prices, w["total"], idx)


def test_extension_after_price_scraper_end_includes_dividends() -> None:
    w = _world(div_day=117)
    idx = w["idx"]
    ps = w["ps"].iloc[:-5]  # price-scraper snapshot ends 5 days earlier
    res = reconcile_ticker("SYN", ps, w["yf"], pd.DatetimeIndex(idx), **KW)
    p = res.prices
    assert (p.loc[idx[-5:], "price_source"] == "yfinance").all()
    assert np.allclose(p["close"], w["printed"])
    assert _ret_equal(p, w["total"], idx)
    ext = [f for f in res.flags if f.code is WarningCode.FILLED_FROM_SECONDARY]
    assert len(ext) == 5 and all(f.severity is Severity.INFO for f in ext)


def test_unsupported_price_scraper_ticker_uses_yfinance() -> None:
    """BIMAS/MAVI-like: no adjusted layer in the price-scraper; yfinance with a correctly recorded split."""
    w = _world()
    idx = w["idx"]
    ps = w["ps"].assign(ps_has_adj=False, ps_adj_close=np.nan)
    yf = w["yf"].copy()
    correct = w["printed"] * np.where(np.arange(N) < BONUS, 0.5, 1.0)  # split-adjusted as yfinance publishes it
    for c, k in [("Open", 0.995), ("High", 1.01), ("Low", 0.99), ("Close", 1.0)]:
        yf[c] = correct * k
    yf["Adj Close"] = correct * np.where(np.arange(N) < DIV, 0.95, 1.0)
    yf.loc[idx[BONUS], "Stock Splits"] = 2.0
    res = reconcile_ticker("SYN", ps, yf, pd.DatetimeIndex(idx), **KW)
    assert np.allclose(res.prices["close"], w["printed"])
    assert _ret_equal(res.prices, w["total"], idx)
    assert any(f.code is WarningCode.ADJUSTMENT_FROM_SECONDARY for f in res.flags)
    assert res.actions.set_index("ex_date").loc[idx[BONUS], "detail"] == "yfinance stock splits 2"


def test_yfinance_only_marks_single_source() -> None:
    w = _world()
    res = reconcile_ticker("IDX", None, w["yf"], pd.DatetimeIndex(w["idx"]), **KW)
    assert len(res.prices) == N
    assert any(f.code is WarningCode.SINGLE_SOURCE for f in res.flags)


def test_phantom_yfinance_row_is_dropped() -> None:
    w = _world()
    idx = w["idx"]
    cal = pd.DatetimeIndex(idx.delete(40))  # day 40 is not a trading day (e.g. market closure)
    res = reconcile_ticker("SYN", w["ps"].drop(index=idx[40]), w["yf"], cal, **KW)
    assert idx[40] not in res.prices.index
    assert any(f.code is WarningCode.PHANTOM_ROW_DROPPED and f.date == idx[40].date() for f in res.flags)


def test_yf_unadjust_splits_restores_printed_prices() -> None:
    idx = pd.bdate_range("2023-01-02", periods=4)
    yf = pd.DataFrame(
        {
            "Open": [10.0] * 4,
            "High": [10.0] * 4,
            "Low": [10.0] * 4,
            "Close": [10.0] * 4,
            "Adj Close": [10.0] * 4,
            "Volume": [100.0] * 4,
            "Dividends": [0.0] * 4,
            "Stock Splits": [0.0, 0.0, 21.0, 0.0],
        },
        index=idx,
    )
    u = yf_unadjust_splits(yf)
    assert list(u["raw_close"]) == [210.0, 210.0, 10.0, 10.0]
    assert list(u["raw_volume"]) == pytest.approx([100 / 21, 100 / 21, 100.0, 100.0])


def test_calendar_majority_and_extension() -> None:
    d = pd.bdate_range("2024-01-01", periods=5)
    bars = {"A": d, "B": d.delete(2), "C": d.delete([2, 3])}
    ext = pd.DatetimeIndex([d[1], *pd.bdate_range("2024-01-08", periods=2)])
    cal = build_trading_calendar(bars, majority=0.6, extension_dates=ext)
    days = list(cal["date"])
    assert d[2] not in days  # only 1/3 had a bar
    assert d[3] in days  # 2/3 >= 0.6
    assert days[-2:] == list(pd.bdate_range("2024-01-08", periods=2))
    assert set(cal["source"]) == {"price_scraper_majority", "xu100_yfinance"}
