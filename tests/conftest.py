"""Shared fixtures. Everything here is synthetic (no real market data) and lives in memory."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date

import pandas as pd
import pytest

from bistharness.data import db


@pytest.fixture
def mem_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    yield conn
    conn.close()


def business_days(start: str, periods: int) -> list[date]:
    return [d.date() for d in pd.bdate_range(start, periods=periods)]


def insert_prices(
    conn: sqlite3.Connection,
    ticker: str,
    days: list[date],
    closes: list[float],
    factors: list[float] | None = None,
    volume: float = 1_000.0,
) -> None:
    factors = factors or [1.0] * len(days)
    conn.executemany(
        "INSERT OR REPLACE INTO prices_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (ticker, d.isoformat(), c, c * 1.01, c * 0.99, c, volume, f, "synthetic", "synthetic", "test")
            for d, c, f in zip(days, closes, factors, strict=True)
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO trading_calendar VALUES (?,?,?)", [(d.isoformat(), "synthetic", None) for d in days]
    )
    conn.commit()
