"""Reshaping of PITRepository price frames into analytics inputs (pure)."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from bistharness.analytics.indicators import OHLCV


def ohlcv(prices: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """One instrument's adjusted OHLCV with a DatetimeIndex (from the long PIT frame)."""
    df = prices[prices["ticker"] == ticker]
    if df.empty:
        raise ValueError(f"no rows for {ticker}")
    out = df.set_index(pd.DatetimeIndex(df["date"]))[list(OHLCV)].astype(float)
    out.index.name = "date"
    return out.sort_index()


def column_matrix(prices: pd.DataFrame, tickers: Sequence[str] | None = None, column: str = "close") -> pd.DataFrame:
    """date x ticker matrix of one column (adjusted close by default)."""
    df = prices if tickers is None else prices[prices["ticker"].isin(list(tickers))]
    wide = df.pivot_table(index="date", columns="ticker", values=column, aggfunc="first")
    wide.index = pd.DatetimeIndex(wide.index)
    wide.columns.name = None
    if tickers is not None:
        wide = wide.reindex(columns=list(tickers))
    return wide.sort_index()
