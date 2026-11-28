"""SQLite schema (temporal memory). Every temporal table has exactly one knowledge-date column:

    prices_daily.date · corporate_actions.ex_date · fundamentals.disclosure_datetime · fundamental_issues.disclosure_datetime
    macro_observations.release_datetime · news_events.published_at · speech_segments.published_at

Reads must go through core.pit.PITRepository, which enforces `<knowledge column> <= as_of`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 3
# Derived tables whose DDL changed in a version; they are dropped on upgrade and rebuilt by their ingest command.
DROPPED_ON_UPGRADE: dict[int, tuple[str, ...]] = {2: ("fundamentals",), 3: ("news_events",)}

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
    ticker        TEXT PRIMARY KEY,
    yahoo         TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('stock', 'index')),
    peer_group    TEXT,
    template      TEXT NOT NULL,
    tms29_applies INTEGER NOT NULL,
    course_sector TEXT,
    aliases       TEXT
);

CREATE TABLE IF NOT EXISTS universe_membership (
    universe_id TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    role        TEXT NOT NULL,          -- core | peer | benchmark | index_member
    valid_from  TEXT NOT NULL,
    valid_to    TEXT,                   -- NULL = still valid
    source      TEXT,
    PRIMARY KEY (universe_id, ticker, role, valid_from)
);

CREATE TABLE IF NOT EXISTS trading_calendar (
    date      TEXT PRIMARY KEY,
    source    TEXT NOT NULL,
    n_tickers INTEGER
);

-- Raw (unadjusted) OHLCV + cumulative back-adjustment factor relative to the snapshot end.
-- Point-in-time adjusted price at as_of:  adj_t = raw_t * cum_factor_t / cum_factor_asof
CREATE TABLE IF NOT EXISTS prices_daily (
    ticker        TEXT NOT NULL,
    date          TEXT NOT NULL,
    open          REAL,
    high          REAL,
    low           REAL,
    close         REAL NOT NULL,
    volume        REAL,
    cum_factor    REAL NOT NULL,
    price_source  TEXT NOT NULL,
    factor_source TEXT NOT NULL,
    ingest_id     TEXT NOT NULL,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS ix_prices_date ON prices_daily(date);

CREATE TABLE IF NOT EXISTS corporate_actions (
    ticker    TEXT NOT NULL,
    ex_date   TEXT NOT NULL,
    ratio     REAL NOT NULL,           -- cum_factor_t / cum_factor_(t-1); 2.0 = 1:1 bonus/split
    kind      TEXT NOT NULL,           -- split | dividend | reverse_split | unlabeled
    source    TEXT NOT NULL,
    detail    TEXT,
    ingest_id TEXT NOT NULL,
    PRIMARY KEY (ticker, ex_date, source)
);

CREATE TABLE IF NOT EXISTS price_quality_flags (
    ticker    TEXT NOT NULL,
    date      TEXT,
    code      TEXT NOT NULL,
    severity  TEXT NOT NULL,
    detail    TEXT,
    ingest_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pqf_ticker_date ON price_quality_flags(ticker, date);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker              TEXT NOT NULL,
    fiscal_period       TEXT NOT NULL,   -- fiscal quarter the value refers to, e.g. 2026Q2 (company fiscal calendar)
    period_start        TEXT,            -- flows: first day of the measured interval; NULL for balance-sheet instants
    period_end          TEXT NOT NULL,
    duration            TEXT NOT NULL,   -- instant | 3M | 6M | 9M | 12M (6M/9M/12M flows are year-to-date as on KAP)
    report_period       TEXT NOT NULL,   -- the report that published the value (a prior-year column is a comparative)
    role                TEXT NOT NULL,   -- current | prior (column of that report)
    disclosure_datetime TEXT NOT NULL,   -- KAP publish time, Europe/Istanbul local = knowledge time
    disclosure_index    INTEGER NOT NULL,-- KAP disclosure id (https://www.kap.org.tr/tr/Bildirim/<id>)
    scope               TEXT NOT NULL,   -- consolidated | solo
    statement           TEXT NOT NULL,   -- balance | income | cashflow
    metric              TEXT NOT NULL,   -- canonical name, config/fundamentals.yaml
    value               REAL,            -- TRY, sign as reported (expenses negative)
    unit                TEXT NOT NULL DEFAULT 'TRY',
    tms29_adjusted      INTEGER,         -- 1 inflation-restated report, 0 nominal, NULL unknown (detected, kap.py)
    source              TEXT NOT NULL,
    source_ref          TEXT,            -- kap:<disclosure_index>#<concept(s)>
    ingest_id           TEXT NOT NULL,
    PRIMARY KEY (ticker, scope, metric, fiscal_period, duration, disclosure_index)
);
CREATE INDEX IF NOT EXISTS ix_fund_disc ON fundamentals(ticker, disclosure_datetime);

CREATE TABLE IF NOT EXISTS fundamental_issues (
    ticker              TEXT NOT NULL,
    disclosure_index    INTEGER NOT NULL,
    disclosure_datetime TEXT NOT NULL,
    code                TEXT NOT NULL,
    severity            TEXT NOT NULL,
    detail              TEXT,
    ingest_id           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fund_issues ON fundamental_issues(ticker, disclosure_datetime);

CREATE TABLE IF NOT EXISTS macro_observations (
    series_code      TEXT NOT NULL,
    obs_date         TEXT NOT NULL,
    value            REAL,
    release_datetime TEXT NOT NULL,
    source           TEXT NOT NULL,
    source_ref       TEXT,
    ingest_id        TEXT NOT NULL,
    PRIMARY KEY (series_code, obs_date, release_datetime)
);

CREATE TABLE IF NOT EXISTS news_events (
    event_id     TEXT PRIMARY KEY,
    published_at TEXT NOT NULL,           -- knowledge time (conservative, see data/ingest/news.py)
    first_published_at TEXT,              -- original publication time (display only)
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    tickers      TEXT,                   -- JSON list
    topics       TEXT,                   -- JSON list
    event_type   TEXT,
    ingest_id    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_news_pub ON news_events(published_at);

CREATE TABLE IF NOT EXISTS speech_segments (
    source_id     TEXT NOT NULL,
    segment_start REAL NOT NULL,
    segment_end   REAL NOT NULL,
    published_at  TEXT NOT NULL,
    url           TEXT,
    speaker       TEXT,
    channel       TEXT,
    text          TEXT,
    topics        TEXT,
    stance        TEXT,
    quality       REAL,
    ingest_id     TEXT NOT NULL,
    PRIMARY KEY (source_id, segment_start)
);

CREATE TABLE IF NOT EXISTS speech_claims (
    claim_id          TEXT PRIMARY KEY,
    source_id         TEXT NOT NULL,
    segment_start     REAL NOT NULL,
    published_at      TEXT NOT NULL,
    segment_sha256    TEXT NOT NULL,
    extraction_sha256 TEXT NOT NULL,
    subject           TEXT NOT NULL,
    claim_type        TEXT NOT NULL,
    quote             TEXT NOT NULL,
    quoted_numbers    TEXT NOT NULL,
    metric            TEXT,
    direction         TEXT NOT NULL,
    horizon_days      INTEGER,
    stance            TEXT NOT NULL,
    certainty         TEXT NOT NULL,
    review_note       TEXT NOT NULL,
    ingest_id         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_speech_claim_pub ON speech_claims(published_at);

CREATE TABLE IF NOT EXISTS ingest_log (
    ingest_id       TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    snapshot        TEXT NOT NULL,
    manifest_sha256 TEXT,
    row_count       INTEGER,
    params          TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    code_version    TEXT
);
"""


def connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if not has_meta:
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row[0]) if row else 0


def init_db(conn: sqlite3.Connection) -> None:
    current = schema_version(conn)
    for version, tables in sorted(DROPPED_ON_UPGRADE.items()):
        if 0 < current < version:
            for table in tables:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(DDL)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
