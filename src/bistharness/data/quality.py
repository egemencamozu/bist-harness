"""Price-series quality checks (pure) and a point-in-time quality report CLI.

uv run python -m bistharness.data.quality --as-of 2026-09-10 [--universe course_30] [--start 2024-01-01]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import numpy as np
import pandas as pd

from bistharness.core.config import load_settings, load_universe
from bistharness.core.dates import require_as_of, to_date
from bistharness.core.enums import HARD_BLOCK_CODES, Severity, WarningCode
from bistharness.core.pit import PITRepository
from bistharness.data.ingest.reconcile import Flag

REL_EPS = 1e-6


def check_ohlc(ticker: str, df: pd.DataFrame) -> list[Flag]:
    """df: index date; raw open/high/low/close."""
    flags: list[Flag] = []
    o, h, low, c = df["open"], df["high"], df["low"], df["close"]
    nonpos = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    for d in df.index[nonpos]:
        flags.append(Flag(ticker, d.date(), WarningCode.NON_POSITIVE_PRICE, Severity.HARD, "price <= 0"))
    hi_bad = h < np.maximum(o, c) * (1 - REL_EPS)
    lo_bad = low > np.minimum(o, c) * (1 + REL_EPS)
    for d in df.index[(hi_bad | lo_bad) & ~nonpos]:
        r = df.loc[d]
        flags.append(
            Flag(
                ticker,
                d.date(),
                WarningCode.OHLC_INCONSISTENT,
                Severity.SOFT,
                f"O={r['open']:g} H={r['high']:g} L={r['low']:g} C={r['close']:g}",
            )
        )
    return flags


def check_jumps(ticker: str, adj_close: pd.Series, *, suspicious: float, broken: float) -> list[Flag]:
    ret = adj_close.pct_change()
    flags: list[Flag] = []
    for d, v in ret[ret.abs() > suspicious].items():
        hard = abs(v) > broken
        flags.append(
            Flag(
                ticker,
                pd.Timestamp(d).date(),
                WarningCode.BROKEN_PRICE_SERIES if hard else WarningCode.SUSPICIOUS_JUMP,
                Severity.HARD if hard else Severity.SOFT,
                f"adjusted daily return {v:+.4f}",
            )
        )
    return flags


def check_stale(ticker: str, close: pd.Series, *, run_days: int) -> list[Flag]:
    """Runs of >= run_days identical consecutive closes (flagged on the day the run reaches run_days)."""
    same = close.diff().eq(0)
    run = same.groupby((~same).cumsum()).cumsum()
    flags = []
    for d in run.index[run == run_days - 1]:
        flags.append(
            Flag(ticker, pd.Timestamp(d).date(), WarningCode.STALE_PRICE, Severity.SOFT, f"{run_days} identical closes")
        )
    return flags


def check_zero_volume(ticker: str, volume: pd.Series) -> list[Flag]:
    return [
        Flag(ticker, pd.Timestamp(d).date(), WarningCode.ZERO_VOLUME, Severity.INFO, "volume == 0")
        for d in volume.index[volume.fillna(0) == 0]
    ]


def run_price_checks(
    ticker: str,
    prices: pd.DataFrame,
    *,
    suspicious: float,
    broken: float,
    stale_days: int,
    is_index: bool = False,
) -> list[Flag]:
    """prices: index date; raw open/high/low/close/volume + cum_factor."""
    if prices.empty:
        return []
    adj_close = prices["close"] * prices["cum_factor"]
    flags = check_ohlc(ticker, prices)
    flags += check_jumps(ticker, adj_close, suspicious=suspicious, broken=broken)
    flags += check_stale(ticker, prices["close"], run_days=stale_days)
    if not is_index:
        flags += check_zero_volume(ticker, prices["volume"])
    return flags


# --------------------------------------------------------------------------- report CLI
def quality_report(repo: PITRepository, tickers: Sequence[str], *, as_of: object, start: object = None) -> pd.DataFrame:
    a = require_as_of(as_of)
    s = to_date(start, name="start") if start is not None else None
    px = repo.prices(list(tickers), s, a, as_of=a).data
    flags = repo.quality_flags(list(tickers), s, a, as_of=a)
    rows = []
    for t in tickers:
        p = px[px["ticker"] == t]
        f = flags[flags["ticker"] == t]
        ret = p["close"].pct_change()
        counts = f["code"].value_counts().to_dict()
        hard = any(WarningCode(c) in HARD_BLOCK_CODES for c in counts)
        rows.append(
            {
                "ticker": t,
                "days": len(p),
                "first": p["date"].min().date() if len(p) else None,
                "last": p["date"].max().date() if len(p) else None,
                "max_abs_ret": round(float(ret.abs().max()), 4) if len(p) > 1 else None,
                "actions": len(repo.corporate_actions(t, as_of=a)),
                "status": "HARD" if hard else ("WARN" if counts else "OK"),
                "flags": ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())),
            }
        )
    return pd.DataFrame(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Point-in-time price quality report")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--universe", default=None)
    parser.add_argument("--start", default=None)
    args = parser.parse_args(argv)
    settings = load_settings()
    universe = load_universe()
    tickers = [*universe.tickers(args.universe), universe.benchmark]
    repo = PITRepository(settings.db_path)
    report = quality_report(repo, tickers, as_of=args.as_of, start=args.start or settings.date("analysis_start"))
    with pd.option_context("display.max_colwidth", 90, "display.width", 200):
        print(report.to_string(index=False))
    print(
        f"\nHARD: {int((report['status'] == 'HARD').sum())}  WARN: {int((report['status'] == 'WARN').sum())}  "
        f"OK: {int((report['status'] == 'OK').sum())}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
