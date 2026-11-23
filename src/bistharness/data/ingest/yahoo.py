"""yfinance adapter. Used only at ingest time (internet); analysis reads the frozen CSV snapshot."""

from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]


def download_history(symbol: str, start: date, end_exclusive: date) -> pd.DataFrame:
    import yfinance as yf  # imported lazily: not needed for offline analysis

    hist = yf.Ticker(symbol).history(
        start=start.isoformat(), end=end_exclusive.isoformat(), auto_adjust=False, actions=True
    )
    if hist.empty:
        return pd.DataFrame(columns=COLUMNS)
    missing = [c for c in COLUMNS if c not in hist.columns]
    if missing:
        raise ValueError(f"{symbol}: yfinance response lacks columns {missing}")
    hist = hist[COLUMNS].copy()
    hist.index = pd.DatetimeIndex(hist.index.tz_localize(None).normalize(), name="Date")
    return hist


def download_many(
    symbols: dict[str, str], start: date, end_exclusive: date, dest_dir: Path, pause_s: float = 0.4
) -> dict[str, int]:
    """symbols: ticker -> yahoo symbol. Writes <dest>/<TICKER>.csv; returns ticker -> row count."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for ticker, symbol in sorted(symbols.items()):
        for attempt in range(3):
            try:
                df = download_history(symbol, start, end_exclusive)
                break
            except Exception as exc:  # network hiccups / rate limits
                log.warning("%s attempt %d failed: %s", symbol, attempt + 1, exc)
                time.sleep(2.0 * (attempt + 1))
        else:
            log.error("%s: giving up", symbol)
            continue
        df.to_csv(dest_dir / f"{ticker}.csv", encoding="utf-8")
        counts[ticker] = len(df)
        time.sleep(pause_s)
    return counts


def load_snapshot_csv(snapshot_dir: Path, ticker: str) -> pd.DataFrame | None:
    path = snapshot_dir / f"{ticker}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["Date"], encoding="utf-8").set_index("Date").sort_index()
    return df


def valid_rows(df: pd.DataFrame) -> pd.Series:
    """True for real trading rows. yfinance emits placeholder rows on holidays/closures:
    volume 0 with O=H=L=C (e.g. 2023-02-08 earthquake closure, bayram days)."""
    close_ok = df["Close"].notna() & (df["Close"] > 0) & df["Adj Close"].notna()
    flat = (df["Open"] == df["High"]) & (df["High"] == df["Low"]) & (df["Low"] == df["Close"])
    placeholder = (df["Volume"].fillna(0) == 0) & flat
    return close_ok & ~placeholder
