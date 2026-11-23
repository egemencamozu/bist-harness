"""Price ingest: freeze raw snapshots, reconcile sources, run quality checks, (re)build the price tables.

A snapshot named D contains only completed sessions strictly before D (an in-progress bar is never stored).
Re-running with an existing snapshot verifies its manifest and never downloads again.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from bistharness import __version__
from bistharness.core.config import Settings, Universe
from bistharness.core.errors import DataNotFoundError
from bistharness.core.hashing import sha256_hex
from bistharness.data import db
from bistharness.data.ingest import manifest as mf
from bistharness.data.ingest import price_scraper as ps_src
from bistharness.data.ingest import yahoo
from bistharness.data.ingest.reconcile import Flag, build_trading_calendar, reconcile_ticker
from bistharness.data.quality import run_price_checks

log = logging.getLogger(__name__)

PS_SOURCE = "price_scraper"
YF_SOURCE = "yfinance"
DOWNLOAD_START = date(2022, 12, 1)  # matches the price-scraper history start


@dataclass
class IngestSummary:
    ingest_id: str
    snapshot: str
    tickers: int
    price_rows: int
    calendar_days: int
    actions: int
    flags: dict[str, int]
    per_source: dict[str, int]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def prepare_price_scraper_snapshot(settings: Settings, universe: Universe, snapshot: str) -> dict[str, object]:
    dest = settings.raw_dir / PS_SOURCE / snapshot
    if (dest / mf.MANIFEST_NAME).exists():
        return mf.verify_manifest(dest)
    src = settings.path("external", "price_scraper_output")
    batches = list(settings.raw["paths"]["external"]["price_scraper_batches"])
    files = ps_src.find_daily_files(src, batches)
    if not files:
        raise DataNotFoundError(f"no price-scraper daily files under {src} {batches}")
    n = ps_src.snapshot_daily_files(files, dest, tickers=list(universe.all_stock_tickers()))
    log.info("copied %d price-scraper files into %s", n, dest)
    return mf.write_manifest(dest, source=PS_SOURCE, params={"origin": src.as_posix(), "batches": batches})


def prepare_yahoo_snapshot(
    settings: Settings, universe: Universe, snapshot: str, *, allow_download: bool
) -> dict[str, object]:
    dest = settings.raw_dir / YF_SOURCE / snapshot
    if (dest / mf.MANIFEST_NAME).exists():
        return mf.verify_manifest(dest)
    if not allow_download:
        raise DataNotFoundError(f"yfinance snapshot {dest} missing and downloads are disabled")
    end_exclusive = date.fromisoformat(snapshot)
    symbols = {t: universe.instrument(t).yahoo for t in [*universe.all_stock_tickers(), universe.benchmark]}
    counts = yahoo.download_many(symbols, DOWNLOAD_START, end_exclusive, dest)
    missing = sorted(set(symbols) - set(counts))
    if missing:
        log.warning("yfinance returned nothing for: %s", missing)
    return mf.write_manifest(
        dest,
        source=YF_SOURCE,
        params={"start": DOWNLOAD_START.isoformat(), "end_exclusive": snapshot, "auto_adjust": False, "actions": True},
    )


def run(
    settings: Settings,
    universe: Universe,
    snapshot: str,
    *,
    allow_download: bool = True,
) -> IngestSummary:
    started = _now()
    cutoff = pd.Timestamp(date.fromisoformat(snapshot))  # keep only sessions strictly before the snapshot day
    ps_manifest = prepare_price_scraper_snapshot(settings, universe, snapshot)
    yf_manifest = prepare_yahoo_snapshot(settings, universe, snapshot, allow_download=allow_download)
    ps_dir = settings.raw_dir / PS_SOURCE / snapshot
    yf_dir = settings.raw_dir / YF_SOURCE / snapshot

    stocks = list(universe.all_stock_tickers())
    bench = universe.benchmark
    ps_frames: dict[str, pd.DataFrame] = {}
    yf_frames: dict[str, pd.DataFrame | None] = {}
    for t in stocks:
        p = ps_src.load_daily(ps_dir, t)
        p = p[p.index < cutoff]
        if not p.empty:
            ps_frames[t] = p
    for t in [*stocks, bench]:
        y = yahoo.load_snapshot_csv(yf_dir, t)
        yf_frames[t] = y[y.index < cutoff] if y is not None else None

    # ------------------------------------------------------------ trading calendar
    xu = yf_frames.get(bench)
    xu_days = xu.index[yahoo.valid_rows(xu)] if xu is not None else None
    cal = build_trading_calendar(
        {t: f.index for t, f in ps_frames.items()},
        majority=settings.threshold("calendar_majority"),
        extension_dates=xu_days,
    )
    calendar = pd.DatetimeIndex(cal["date"])

    # ------------------------------------------------------------ reconcile + checks
    ingest_id = f"prices-{snapshot}-" + sha256_hex([ps_manifest["content_sha256"], yf_manifest["content_sha256"]])[:10]
    all_prices: list[pd.DataFrame] = []
    all_actions: list[pd.DataFrame] = []
    all_flags: list[Flag] = []
    suspicious = settings.threshold("suspicious_jump")
    broken = settings.threshold("broken_jump")
    stale_days = int(settings.threshold("stale_run_days"))
    for t in [*stocks, bench]:
        res = reconcile_ticker(
            t,
            ps_frames.get(t),
            yf_frames.get(t),
            calendar,
            band=settings.threshold("suspicious_jump"),
            min_log_change=float(settings.raw["corporate_actions"]["min_log_change"]),
            source_disagreement=settings.threshold("source_disagreement"),
        )
        if res.prices.empty:
            log.error("%s: no usable price data", t)
            continue
        pr = res.prices.reset_index().assign(ticker=t)
        all_prices.append(pr)
        if len(res.actions):
            all_actions.append(res.actions.assign(ticker=t))
        all_flags += res.flags
        all_flags += run_price_checks(
            t, res.prices, suspicious=suspicious, broken=broken, stale_days=stale_days, is_index=(t == bench)
        )

    prices = pd.concat(all_prices, ignore_index=True)
    actions = pd.concat(all_actions, ignore_index=True) if all_actions else pd.DataFrame()
    flags = pd.DataFrame([f.as_row() for f in all_flags], columns=["ticker", "date", "code", "severity", "detail"])

    # ------------------------------------------------------------ write (full rebuild of price tables)
    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        _write(conn, universe, cal, prices, actions, flags, ingest_id)
        conn.execute(
            "INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ingest_id,
                "prices",
                snapshot,
                sha256_hex([ps_manifest["content_sha256"], yf_manifest["content_sha256"]]),
                len(prices),
                json.dumps({"price_scraper": ps_manifest["content_sha256"], "yfinance": yf_manifest["content_sha256"]}),
                started,
                _now(),
                __version__,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return IngestSummary(
        ingest_id=ingest_id,
        snapshot=snapshot,
        tickers=prices["ticker"].nunique(),
        price_rows=len(prices),
        calendar_days=len(cal),
        actions=len(actions),
        flags=flags["code"].value_counts().to_dict() if len(flags) else {},
        per_source=prices["price_source"].value_counts().to_dict(),
    )


def _write(
    conn: sqlite3.Connection,
    universe: Universe,
    cal: pd.DataFrame,
    prices: pd.DataFrame,
    actions: pd.DataFrame,
    flags: pd.DataFrame,
    ingest_id: str,
) -> None:
    for table in (
        "instruments",
        "universe_membership",
        "trading_calendar",
        "prices_daily",
        "corporate_actions",
        "price_quality_flags",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.executemany(
        "INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                i.ticker,
                i.yahoo,
                i.kind,
                i.peer_group,
                i.template.value,
                int(i.tms29_applies),
                i.course_sector,
                json.dumps(list(i.aliases)),
            )
            for i in universe.instruments.values()
        ],
    )
    first_day = cal["date"].min().date().isoformat()
    membership = [
        (uid, t, "core", first_day, None, "config/universe.yaml") for uid, ts in universe.universes.items() for t in ts
    ]
    membership.append(("benchmark", universe.benchmark, "benchmark", first_day, None, "config/universe.yaml"))
    conn.executemany("INSERT INTO universe_membership VALUES (?,?,?,?,?,?)", membership)
    conn.executemany(
        "INSERT INTO trading_calendar VALUES (?,?,?)",
        [
            (d.date().isoformat(), s, None if pd.isna(n) else int(n))
            for d, s, n in cal[["date", "source", "n_tickers"]].itertuples(index=False)
        ],
    )
    conn.executemany(
        "INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                r.ticker,
                r.date.date().isoformat(),
                _f(r.open),
                _f(r.high),
                _f(r.low),
                float(r.close),
                _f(r.volume),
                float(r.cum_factor),
                r.price_source,
                r.factor_source,
                ingest_id,
            )
            for r in prices.itertuples(index=False)
        ],
    )
    if len(actions):
        conn.executemany(
            "INSERT OR REPLACE INTO corporate_actions VALUES (?,?,?,?,?,?,?)",
            [
                (
                    r.ticker,
                    pd.Timestamp(r.ex_date).date().isoformat(),
                    _f(r.ratio),
                    r.kind,
                    r.source,
                    r.detail,
                    ingest_id,
                )
                for r in actions.itertuples(index=False)
            ],
        )
    if len(flags):
        conn.executemany(
            "INSERT INTO price_quality_flags VALUES (?,?,?,?,?,?)",
            [(r.ticker, r.date, r.code, r.severity, r.detail, ingest_id) for r in flags.itertuples(index=False)],
        )


def _f(v: object) -> float | None:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if pd.isna(x) else x


def default_snapshot_name(today: date | None = None) -> str:
    return (today or date.today()).isoformat()


__all__ = ["IngestSummary", "default_snapshot_name", "run"]
