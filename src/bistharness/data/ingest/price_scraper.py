"""Adapter for the FinTreX price-scraper output (investing.com intraday-derived daily bars).

File layout: <output>/<batch>/<TICKER>_gunluk_<from>_<to>.json with {"metadata": {...}, "bars": [...]}.
Bars carry raw open/high/low/close/volume; some files also carry adj_* (bonus/rights only, never dividends).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pandas as pd

DAILY_RE = re.compile(r"^(?P<ticker>[A-Z0-9]+)_gunluk_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.json$")


def find_daily_files(output_dir: Path, batches: list[str]) -> dict[str, list[Path]]:
    """Map ticker -> its daily JSON files across the given batch folders (stale *_eski folders are not passed in)."""
    found: dict[str, list[Path]] = {}
    for batch in batches:
        folder = output_dir / batch
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            m = DAILY_RE.match(p.name)
            if m:
                found.setdefault(m.group("ticker"), []).append(p)
    return found


def snapshot_daily_files(files: dict[str, list[Path]], dest_dir: Path, tickers: list[str] | None = None) -> int:
    """Copy daily JSONs into the frozen snapshot folder (flat layout). Returns the number of files copied."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for ticker, paths in sorted(files.items()):
        if tickers is not None and ticker not in tickers:
            continue
        for p in paths:
            shutil.copy2(p, dest_dir / p.name)
            n += 1
    return n


def load_daily(snapshot_dir: Path, ticker: str) -> pd.DataFrame:
    """All daily bars of one ticker from a snapshot, indexed by date (DatetimeIndex, naive).

    Columns: open, high, low, close, volume, ps_adj_close (NaN where the file had no adjusted layer),
    ps_has_adj (bool).
    """
    parts: list[pd.DataFrame] = []
    for p in sorted(snapshot_dir.glob(f"{ticker}_gunluk_*.json")):
        payload = json.loads(p.read_text(encoding="utf-8"))
        bars = pd.DataFrame(payload["bars"])
        if bars.empty:
            continue
        has_adj = "adj_close" in bars.columns
        out = pd.DataFrame(
            {
                "date": pd.to_datetime(bars["time"].str[:10]),
                "open": bars["open"].astype(float),
                "high": bars["high"].astype(float),
                "low": bars["low"].astype(float),
                "close": bars["close"].astype(float),
                "volume": bars["volume"].astype(float),
                "ps_adj_close": bars["adj_close"].astype(float) if has_adj else float("nan"),
                "ps_has_adj": has_adj,
            }
        )
        parts.append(out)
    if not parts:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume", "ps_adj_close", "ps_has_adj"],
            index=pd.DatetimeIndex([], name="date"),
        )
    df = pd.concat(parts, ignore_index=True)
    df = df.drop_duplicates(subset="date", keep="last").sort_values("date").set_index("date")
    return df
