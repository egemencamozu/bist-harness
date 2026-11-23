"""Synthetic market data for tests only (never real prices; CLAUDE.md §1.8)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_ohlcv(n: int = 600, seed: int = 42, start: str = "2023-01-02", vol: float = 0.02) -> pd.DataFrame:
    """Business-day OHLCV with alternating up/down regimes (so flips, breakouts and pivots occur)."""
    rng = np.random.default_rng(seed)
    regime = np.repeat(rng.choice([-1.0, 1.0], size=n // 40 + 1), 40)[:n]
    rets = rng.normal(0.0015 * regime, vol, n)
    close = 100 * np.exp(np.cumsum(rets))
    open_ = close * np.exp(rng.normal(0, vol / 3, n))
    hi = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, vol / 2, n)))
    volume = rng.lognormal(13, 0.4, n)
    idx = pd.bdate_range(start, periods=n, name="date")
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close, "volume": volume}, index=idx)


def synthetic_closes(tickers: list[str], n: int = 400, seed: int = 7, start: str = "2023-01-02") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n, name="date")
    data = {t: 50 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n))) for t in tickers}
    return pd.DataFrame(data, index=idx)
