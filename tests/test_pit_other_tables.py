"""Point-in-time behaviour of fundamentals (restatements), macro (vintages) and news."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime

import pytest

from bistharness.core.pit import PITRepository

FUND_COLS = (
    "ticker, fiscal_period, period_start, period_end, duration, report_period, role, disclosure_datetime, "
    "disclosure_index, scope, statement, metric, value, unit, tms29_adjusted, source, source_ref, ingest_id"
)
_next_idx = iter(range(1000, 100000))


def _fund(
    conn: sqlite3.Connection,
    period: str,
    disclosed: str,
    metric: str,
    value: float | None,
    *,
    role: str = "current",
    report_period: str | None = None,
    idx: int | None = None,
) -> None:
    conn.execute(
        f"INSERT INTO fundamentals ({FUND_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "TUPRS",
            period,
            f"{period[:4]}-01-01",
            "2026-06-30",
            "6M",
            report_period or period,
            role,
            disclosed,
            idx if idx is not None else next(_next_idx),
            "consolidated",
            "income",
            metric,
            value,
            "TRY",
            1,
            "synthetic",
            None,
            "t",
        ),
    )


@pytest.fixture
def fund_conn(mem_conn: sqlite3.Connection) -> sqlite3.Connection:
    _fund(mem_conn, "2026Q1", "2026-05-08 18:45:00", "revenue", 100.0)
    _fund(mem_conn, "2026Q2", "2026-08-14 19:02:11", "revenue", 210.0)
    _fund(mem_conn, "2026Q2", "2026-09-20 18:30:00", "revenue", 205.0)  # restatement after as_of
    _fund(mem_conn, "2026Q3", "2026-11-06 18:20:00", "revenue", 330.0)  # future quarter (poison)
    mem_conn.commit()
    return mem_conn


def test_future_disclosures_are_invisible(fund_conn: sqlite3.Connection) -> None:
    df = PITRepository(fund_conn).fundamentals("TUPRS", as_of="2026-09-10").data
    assert set(df["fiscal_period"]) == {"2026Q1", "2026Q2"}


def test_restatement_respects_as_of(fund_conn: sqlite3.Connection) -> None:
    repo = PITRepository(fund_conn)
    before = repo.fundamentals("TUPRS", as_of="2026-09-10").data
    after = repo.fundamentals("TUPRS", as_of="2026-09-30").data
    q2_before = before[before["fiscal_period"] == "2026Q2"].iloc[0]
    q2_after = after[after["fiscal_period"] == "2026Q2"].iloc[0]
    assert q2_before["value"] == 210.0 and q2_before["n_versions"] == 1
    assert q2_after["value"] == 205.0 and q2_after["n_versions"] == 2


def test_disclosure_on_as_of_evening_counts_as_known(fund_conn: sqlite3.Connection) -> None:
    df = PITRepository(fund_conn).fundamentals("TUPRS", as_of="2026-08-14").data
    assert "2026Q2" in set(df["fiscal_period"])
    df_prev = PITRepository(fund_conn).fundamentals("TUPRS", as_of="2026-08-13").data
    assert "2026Q2" not in set(df_prev["fiscal_period"])


def test_intraday_cutoff_filters_before_selecting_a_fundamental_revision(fund_conn: sqlite3.Connection) -> None:
    _fund(fund_conn, "2026Q2", "2026-08-14 21:00:00", "revenue", 999.0)
    repo = PITRepository(fund_conn)
    cutoff = datetime(2026, 8, 14, 19, 2, 11)
    before = repo.fundamentals("TUPRS", as_of="2026-08-14", knowledge_cutoff=cutoff).data
    assert before.set_index("fiscal_period").loc["2026Q2", "value"] == 210.0
    earlier = repo.fundamentals("TUPRS", as_of="2026-08-13", knowledge_cutoff=cutoff).data
    assert "2026Q2" not in set(earlier["fiscal_period"])
    with pytest.raises(ValueError, match="Istanbul"):
        repo.fundamentals("TUPRS", as_of="2026-08-14", knowledge_cutoff=cutoff.replace(tzinfo=UTC))


def test_nan_restatement_is_not_hidden_by_older_value(mem_conn: sqlite3.Connection) -> None:
    _fund(mem_conn, "2026Q2", "2026-08-14 19:00:00", "ebitda", 50.0)
    _fund(mem_conn, "2026Q2", "2026-08-20 19:00:00", "ebitda", None)
    mem_conn.commit()
    df = PITRepository(mem_conn).fundamentals("TUPRS", as_of="2026-09-10").data
    assert df.iloc[0]["value"] != df.iloc[0]["value"]  # NaN: the latest disclosure wins even when empty


def test_comparative_columns_are_not_versions_unless_asked(mem_conn: sqlite3.Connection) -> None:
    _fund(mem_conn, "2025Q2", "2025-07-29 18:33:39", "revenue", 100.0)
    _fund(mem_conn, "2025Q2", "2026-08-04 18:24:32", "revenue", 132.0, role="prior", report_period="2026Q2")
    mem_conn.commit()
    repo = PITRepository(mem_conn)
    as_reported = repo.fundamentals("TUPRS", as_of="2026-09-10").data
    assert as_reported.iloc[0]["value"] == 100.0 and as_reported.iloc[0]["n_versions"] == 1
    restated = repo.fundamentals("TUPRS", as_of="2026-09-10", role=None).data
    assert restated.iloc[0]["value"] == 132.0 and restated.iloc[0]["report_period"] == "2026Q2"
    before = repo.fundamentals("TUPRS", as_of="2026-08-03", role=None).data
    assert before.iloc[0]["value"] == 100.0  # the restating report was not yet published
    every = repo.fundamentals("TUPRS", as_of="2026-09-10", role=None, latest_only=False).data
    assert len(every) == 2


def test_fundamental_reports_lists_only_published_reports(fund_conn: sqlite3.Connection) -> None:
    repo = PITRepository(fund_conn)
    assert list(repo.fundamental_reports("TUPRS", as_of="2026-09-10")["report_period"]) == ["2026Q1", "2026Q2"]
    later = repo.fundamental_reports("TUPRS", as_of="2026-09-30")
    assert list(later["report_period"]) == ["2026Q1", "2026Q2", "2026Q2"]  # the correction is its own report


def test_macro_uses_release_time_not_observation_date(mem_conn: sqlite3.Connection) -> None:
    rows = [
        ("TUFE_YOY", "2026-08-01", 33.0, "2026-09-03 10:00:00"),  # August CPI released 3 Sep
        ("TUFE_YOY", "2026-09-01", 31.0, "2026-10-05 10:00:00"),  # September CPI released after as_of
        ("TUFE_YOY", "2026-08-01", 33.4, "2026-10-05 10:00:00"),  # revision of August after as_of
    ]
    mem_conn.executemany(
        "INSERT INTO macro_observations VALUES (?,?,?,?,?,?,?)", [(*r, "synthetic", None, "t") for r in rows]
    )
    mem_conn.commit()
    repo = PITRepository(mem_conn)
    df = repo.macro("TUFE_YOY", "2026-01-01", "2026-12-31", as_of="2026-09-10").data
    assert list(df["obs_date"]) == ["2026-08-01"]
    assert df.iloc[0]["value"] == 33.0
    later = repo.macro("TUFE_YOY", "2026-01-01", "2026-12-31", as_of=date(2026, 10, 31)).data
    assert later.set_index("obs_date").loc["2026-08-01", "value"] == 33.4
    intraday = repo.macro("TUFE_YOY", as_of="2026-10-05", knowledge_cutoff=datetime(2026, 10, 5, 9)).data
    assert list(intraday["obs_date"]) == ["2026-08-01"]
    assert intraday.iloc[0]["value"] == 33.0


def test_news_after_as_of_is_invisible(mem_conn: sqlite3.Connection) -> None:
    mem_conn.executemany(
        "INSERT INTO news_events (event_id, published_at, first_published_at, source, title, url, tickers, topics, "
        "event_type, ingest_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("n1", "2026-09-10 21:00:00", None, "synthetic", "old", None, json.dumps(["EREGL"]), "[]", None, "t"),
            # first published before as_of, but the archived version only exists after it -> invisible
            (
                "n2",
                "2026-09-11 08:00:00",
                "2026-09-10 12:00:00",
                "synthetic",
                "edited",
                None,
                '["EREGL"]',
                "[]",
                None,
                "t",
            ),
        ],
    )
    mem_conn.commit()
    df = PITRepository(mem_conn).news(as_of="2026-09-10", ticker="EREGL").data
    assert list(df["event_id"]) == ["n1"]
