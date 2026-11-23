"""Fundamentals ingest: freeze the universe's KAP financial reports, parse them, rebuild the fundamentals tables.

Snapshot `D` = every 'Finansal Rapor' disclosure published strictly before day `D`, extracted from the user's KAP dump
(`paths.external.kapdata`) into `data/raw/kap/<D>/financial_reports.jsonl.gz` (deterministic gzip, sorted by
disclosure id) with a sha256 manifest. Re-running with an existing snapshot verifies the manifest and re-parses it.
The last publish time is stored in meta `fundamentals_coverage_end`: tools warn when as_of is later than that.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from bistharness import __version__
from bistharness.core.config import Settings, Universe
from bistharness.core.errors import DataNotFoundError
from bistharness.core.hashing import file_sha256, sha256_hex
from bistharness.data import db
from bistharness.data.ingest import kap
from bistharness.data.ingest import manifest as mf

log = logging.getLogger(__name__)

KAP_SOURCE = "kap"
SNAPSHOT_FILE = "financial_reports.jsonl.gz"
MAP_FILE = Path("config") / "fundamentals.yaml"


@dataclass
class FundamentalsSummary:
    ingest_id: str
    snapshot: str
    reports: int
    tickers: int
    rows: int
    coverage_end: str
    missing_tickers: list[str]
    issues: dict[str, int]
    metric_coverage: pd.DataFrame  # format x metric -> share of reports with a current value
    tms29: pd.DataFrame  # ticker, scope, config tms29_applies, detected (latest post-2023 report), mismatch


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _codes(universe: Universe) -> tuple[set[str], dict[str, str]]:
    tickers = set(universe.all_stock_tickers())
    aliases = {a: t for t in tickers for a in universe.instrument(t).aliases}
    return tickers, aliases


def _rel(path: Path, root: Path) -> str:
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:  # different drive on Windows
        return path.as_posix()


def prepare_kap_snapshot(settings: Settings, universe: Universe, snapshot: str) -> dict[str, Any]:
    dest = settings.raw_dir / KAP_SOURCE / snapshot
    if (dest / mf.MANIFEST_NAME).exists():
        return mf.verify_manifest(dest)
    src = settings.path("external", "kapdata")
    files = sorted(src.glob("*.jsonl"))
    if not files:
        raise DataNotFoundError(f"no KAP dump files (*.jsonl) under {src}")
    tickers, aliases = _codes(universe)
    cutoff = f"{snapshot} 00:00:00"
    records = [
        r for r in kap.iter_financial_reports(files, tickers | set(aliases)) if str(r.get("publish_date")) < cutoff
    ]
    records.sort(key=lambda r: int(r["disclosure_index"]))
    dest.mkdir(parents=True, exist_ok=True)
    # mtime=0 + empty name -> byte-identical file on re-runs
    with (dest / SNAPSHOT_FILE).open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8", newline="\n")
        for r in records:
            text.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        text.flush()
        text.detach()
    pubs = [str(r["publish_date"]) for r in records]
    params = {
        "origin": _rel(src, settings.root),
        "source_files": {f.name: {"bytes": f.stat().st_size, "sha256": file_sha256(f)} for f in files},
        "filter": f"title == '{kap.TITLE}' and stock_code in universe and publish_date < {cutoff}",
        "records": len(records),
        "first_publish": min(pubs) if pubs else None,
        "last_publish": max(pubs) if pubs else None,
    }
    log.info("froze %d KAP financial reports into %s", len(records), dest)
    return mf.write_manifest(dest, source=KAP_SOURCE, params=params)


def load_snapshot(settings: Settings, snapshot: str) -> list[dict[str, Any]]:
    path = settings.raw_dir / KAP_SOURCE / snapshot / SNAPSHOT_FILE
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def parse_all(
    records: list[dict[str, Any]], universe: Universe, fmap: kap.FundamentalsMap
) -> tuple[pd.DataFrame, list[kap.Issue], list[kap.ParsedReport]]:
    tickers, aliases = _codes(universe)
    rows: list[dict[str, object]] = []
    issues: list[kap.Issue] = []
    reports: list[kap.ParsedReport] = []
    for rec in records:
        ticker = kap.resolve_ticker(rec.get("stock_code"), tickers, aliases)
        if ticker is None:
            log.warning(
                "disclosure %s: cannot resolve %r to one universe ticker",
                rec.get("disclosure_index"),
                rec.get("stock_code"),
            )
            continue
        rep = kap.parse_report(rec, ticker, fmap)
        reports.append(rep)
        rows += rep.rows
        issues += rep.issues
    return pd.DataFrame(rows, columns=kap.ROW_COLUMNS), issues, reports


def run(settings: Settings, universe: Universe, snapshot: str) -> FundamentalsSummary:
    started = _now()
    manifest = prepare_kap_snapshot(settings, universe, snapshot)
    fmap_path = settings.root / MAP_FILE
    fmap = kap.load_fundamentals_map(fmap_path)
    records = load_snapshot(settings, snapshot)
    rows, issues, reports = parse_all(records, universe, fmap)

    tms = kap.detect_tms29(rows, fmap)
    rows = rows.merge(tms[["disclosure_index", "tms29_adjusted"]], on="disclosure_index", how="left")
    # data version = raw snapshot + mapping config: changing either changes every downstream call_id
    version = sha256_hex([manifest["content_sha256"], file_sha256(fmap_path)])
    ingest_id = f"fundamentals-{snapshot}-{version[:10]}"
    coverage_end = str(manifest["params"].get("last_publish") or "")

    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        _write(conn, rows, issues, ingest_id)
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('fundamentals_coverage_end', ?)", (coverage_end,))
        conn.execute(
            "INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ingest_id,
                "fundamentals",
                snapshot,
                version,
                len(rows),
                json.dumps({"kap": manifest["content_sha256"], "mapping_sha256": file_sha256(fmap_path)}),
                started,
                _now(),
                __version__,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return FundamentalsSummary(
        ingest_id=ingest_id,
        snapshot=snapshot,
        reports=len(reports),
        tickers=rows["ticker"].nunique(),
        rows=len(rows),
        coverage_end=coverage_end,
        missing_tickers=sorted(set(universe.all_stock_tickers()) - set(rows["ticker"])),
        issues=dict(Counter(i.code.value for i in issues)),
        metric_coverage=metric_coverage(rows, reports, fmap),
        tms29=tms29_overview(rows, universe),
    )


def metric_coverage(rows: pd.DataFrame, reports: list[kap.ParsedReport], fmap: kap.FundamentalsMap) -> pd.DataFrame:
    """Share of reports (per statement format) that yield a current-period value for each metric."""
    n_reports = Counter(r.fmt for r in reports)
    fmt_of = {r.disclosure_index: r.fmt for r in reports}
    cur = rows[rows["role"] == "current"][["disclosure_index", "metric"]].drop_duplicates()
    cur = cur.assign(fmt=cur["disclosure_index"].map(fmt_of))
    hits = cur.groupby(["fmt", "metric"]).size()
    out = [
        {
            "format": fmt,
            "metric": spec.metric,
            "statement": spec.statement,
            "reports": n_reports[fmt],
            "coverage": round(float(hits.get((fmt, spec.metric), 0)) / max(n_reports[fmt], 1), 3),
        }
        for fmt, specs in fmap.formats.items()
        for spec in specs
    ]
    return pd.DataFrame(out)


def tms29_overview(rows: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    """Detected TMS 29 status of each ticker's latest report vs config/universe.yaml `tms29_applies`."""
    cur = rows[(rows["role"] == "current") & (rows["period_end"] >= "2023-12-31")]
    latest = cur.sort_values(["disclosure_datetime", "disclosure_index"]).groupby(["ticker", "scope"]).tail(1)
    out = latest[["ticker", "scope", "report_period", "tms29_adjusted"]].drop_duplicates(["ticker", "scope"])
    out = out.assign(config_tms29_applies=out["ticker"].map(lambda t: universe.instrument(t).tms29_applies))
    out = out.assign(
        mismatch=out["tms29_adjusted"].notna() & (out["tms29_adjusted"].astype(bool) != out["config_tms29_applies"])
    )
    return out.sort_values(["mismatch", "ticker", "scope"], ascending=[False, True, True]).reset_index(drop=True)


def _write(conn: sqlite3.Connection, rows: pd.DataFrame, issues: list[kap.Issue], ingest_id: str) -> None:
    conn.execute("DELETE FROM fundamentals")
    conn.execute("DELETE FROM fundamental_issues")

    def tms(v: object) -> int | None:
        return None if v is None or pd.isna(v) else int(bool(v))

    conn.executemany(
        "INSERT INTO fundamentals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                r.ticker,
                r.fiscal_period,
                r.period_start,
                r.period_end,
                r.duration,
                r.report_period,
                r.role,
                r.disclosure_datetime,
                int(r.disclosure_index),
                r.scope,
                r.statement,
                r.metric,
                None if pd.isna(r.value) else float(r.value),
                "TRY",
                tms(r.tms29_adjusted),
                "kap_xbrl",
                r.source_ref,
                ingest_id,
            )
            for r in rows.itertuples(index=False)
        ],
    )
    conn.executemany(
        "INSERT INTO fundamental_issues VALUES (?,?,?,?,?,?,?)",
        [
            (i.ticker, i.disclosure_index, i.disclosure_datetime, i.code.value, i.severity.value, i.detail, ingest_id)
            for i in issues
        ],
    )


__all__ = ["FundamentalsSummary", "load_snapshot", "parse_all", "prepare_kap_snapshot", "run"]
