"""Point-in-time repository: the ONLY sanctioned read path for temporal data (CLAUDE.md §2).

Guarantees, for every method:
1. `as_of` is keyword-only and mandatory (None/empty -> AsOfRequiredError).
2. The SQL always contains `<knowledge column> <= :as_of`.
3. A post-check re-verifies the returned rows and raises LookAheadError on any violation.
4. `end > as_of` is clamped to as_of and reported as END_CLAMPED_TO_AS_OF.
5. Adjusted prices are anchored at as_of: corporate actions after as_of cannot influence any output.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from bistharness.core.calendar import TradingCalendar
from bistharness.core.dates import as_of_end_of_day, fmt_date, knowledge_bound, require_as_of, to_date
from bistharness.core.enums import Severity, WarningCode
from bistharness.core.errors import DataNotFoundError, LookAheadError
from bistharness.core.schemas import WarningItem


@dataclass
class PITFrame:
    data: pd.DataFrame
    as_of: date
    start: date | None
    end: date | None
    warnings: list[WarningItem] = field(default_factory=list)


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


class PITRepository:
    def __init__(self, conn_or_path: sqlite3.Connection | Path) -> None:
        if isinstance(conn_or_path, sqlite3.Connection):
            self._conn = conn_or_path
        else:
            if not conn_or_path.exists():
                raise DataNotFoundError(f"database not found: {conn_or_path} (run the ingest first)")
            uri = f"{conn_or_path.resolve().as_uri()}?mode=ro"
            # read-only; the MCP server calls tools from worker threads
            self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)

    @classmethod
    def from_settings(cls) -> PITRepository:
        from bistharness.core.config import load_settings

        return cls(load_settings().db_path)

    # ------------------------------------------------------------------ helpers
    def _read(self, sql: str, params: Sequence[Any]) -> pd.DataFrame:
        return pd.read_sql_query(sql, self._conn, params=list(params))

    @staticmethod
    def _post_check(df: pd.DataFrame, column: str, bound: str, what: str) -> None:
        if df.empty:
            return
        violating = df[df[column].astype(str) > bound]
        if not violating.empty:
            raise LookAheadError(
                f"{what}: {len(violating)} row(s) with {column} > {bound} reached the caller "
                f"(first: {violating[column].astype(str).min()})"
            )

    @staticmethod
    def _clamp(start: Any, end: Any, as_of: date) -> tuple[date | None, date | None, list[WarningItem]]:
        warnings: list[WarningItem] = []
        s = to_date(start, name="start") if start is not None else None
        e = to_date(end, name="end") if end is not None else None
        if e is None or e > as_of:
            if e is not None:
                warnings.append(
                    WarningItem(
                        code=WarningCode.END_CLAMPED_TO_AS_OF,
                        severity=Severity.INFO,
                        detail=f"end {fmt_date(e)} clamped to as_of {fmt_date(as_of)}",
                    )
                )
            e = as_of
        if s is not None and s > e:
            raise ValueError(f"start {s} is after effective end {e}")
        return s, e, warnings

    # ------------------------------------------------------------------ metadata
    def data_version(self) -> dict[str, str]:
        df = self._read(
            "SELECT source, manifest_sha256 FROM ingest_log WHERE finished_at IS NOT NULL ORDER BY started_at",
            (),
        )
        return {str(r.source): str(r.manifest_sha256) for r in df.itertuples()}

    def last_calendar_date(self) -> date | None:
        row = self._conn.execute("SELECT MAX(date) FROM trading_calendar").fetchone()
        return date.fromisoformat(row[0]) if row and row[0] else None

    def _beyond_data_warning(self, as_of: date) -> list[WarningItem]:
        last = self.last_calendar_date()
        if last is not None and as_of > last:
            return [
                WarningItem(
                    code=WarningCode.AS_OF_BEYOND_DATA,
                    severity=Severity.INFO,
                    detail=f"as_of {fmt_date(as_of)} is after the last stored trading day {fmt_date(last)}",
                )
            ]
        return []

    # ------------------------------------------------------------------ calendar
    def trading_calendar(self, *, as_of: Any) -> TradingCalendar:
        a = require_as_of(as_of)
        bound = fmt_date(a)
        df = self._read("SELECT date FROM trading_calendar WHERE date <= ? ORDER BY date", (bound,))
        self._post_check(df, "date", bound, "trading_calendar")
        return TradingCalendar((date.fromisoformat(d) for d in df["date"]), as_of=a)

    # ------------------------------------------------------------------ prices
    def prices(
        self,
        tickers: Sequence[str] | str,
        start: Any = None,
        end: Any = None,
        *,
        as_of: Any,
    ) -> PITFrame:
        """Adjusted OHLCV anchored at as_of.

        Columns: ticker, date, open, high, low, close, volume (adjusted, as_of-anchored),
        raw_open/high/low/close/volume, factor_rel (= cum_factor_t / cum_factor_asof), price_source.
        """
        a = require_as_of(as_of)
        tick = [tickers] if isinstance(tickers, str) else list(tickers)
        if not tick:
            raise ValueError("at least one ticker is required")
        s, e, warnings = self._clamp(start, end, a)
        assert e is not None
        bound = fmt_date(a)

        params: list[Any] = [*tick, fmt_date(e), bound]
        sql = (
            "SELECT ticker, date, open, high, low, close, volume, cum_factor, price_source "
            f"FROM prices_daily WHERE ticker IN ({_placeholders(len(tick))}) AND date <= ? AND date <= ?"
        )
        if s is not None:
            sql += " AND date >= ?"
            params.append(fmt_date(s))
        sql += " ORDER BY ticker, date"
        df = self._read(sql, params)
        self._post_check(df, "date", bound, "prices_daily")

        # anchor factor = cum_factor on the last stored day <= as_of, per ticker
        anchor = self._read(
            "SELECT p.ticker, p.cum_factor AS anchor FROM prices_daily p JOIN ("
            "  SELECT ticker, MAX(date) AS d FROM prices_daily "
            f"  WHERE date <= ? AND ticker IN ({_placeholders(len(tick))}) GROUP BY ticker"
            ") m ON p.ticker = m.ticker AND p.date = m.d",
            [bound, *tick],
        )
        missing = sorted(set(tick) - set(anchor["ticker"]))
        if missing:
            raise DataNotFoundError(f"no price data on or before {bound} for: {missing}")

        df = df.merge(anchor, on="ticker", how="left")
        df["factor_rel"] = df["cum_factor"] / df["anchor"]
        for col in ("open", "high", "low", "close", "volume"):
            df[f"raw_{col}"] = df[col]
        for col in ("open", "high", "low", "close"):
            df[col] = df[f"raw_{col}"] * df["factor_rel"]
        df["volume"] = df["raw_volume"] / df["factor_rel"]  # turnover-preserving
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop(columns=["cum_factor", "anchor"])

        warnings.extend(self._beyond_data_warning(a))
        return PITFrame(data=df.reset_index(drop=True), as_of=a, start=s, end=e, warnings=warnings)

    def corporate_actions(self, ticker: str, *, as_of: Any) -> pd.DataFrame:
        a = require_as_of(as_of)
        bound = fmt_date(a)
        df = self._read(
            "SELECT ticker, ex_date, ratio, kind, source, detail FROM corporate_actions "
            "WHERE ticker = ? AND ex_date <= ? ORDER BY ex_date",
            (ticker, bound),
        )
        self._post_check(df, "ex_date", bound, "corporate_actions")
        return df

    def quality_flags(
        self, tickers: Sequence[str] | str, start: Any = None, end: Any = None, *, as_of: Any
    ) -> pd.DataFrame:
        """Stored price-quality flags dated on/before as_of (undated, series-level flags are always included)."""
        a = require_as_of(as_of)
        tick = [tickers] if isinstance(tickers, str) else list(tickers)
        s, e, _ = self._clamp(start, end, a)
        assert e is not None
        bound = fmt_date(a)
        params: list[Any] = [*tick, fmt_date(e), bound]
        sql = (
            "SELECT ticker, date, code, severity, detail FROM price_quality_flags "
            f"WHERE ticker IN ({_placeholders(len(tick))}) AND (date IS NULL OR (date <= ? AND date <= ?"
        )
        if s is not None:
            sql += " AND date >= ?"
            params.append(fmt_date(s))
        sql += ")) ORDER BY ticker, date"
        df = self._read(sql, params)
        self._post_check(df.dropna(subset=["date"]), "date", bound, "price_quality_flags")
        return df

    # ------------------------------------------------------------------ fundamentals
    _FUND_COLS = (
        "ticker, fiscal_period, period_start, period_end, duration, report_period, role, disclosure_datetime, "
        "disclosure_index, scope, statement, metric, value, unit, tms29_adjusted, source, source_ref"
    )

    def fundamentals(
        self,
        ticker: str,
        start: Any = None,
        end: Any = None,
        *,
        as_of: Any,
        metrics: Sequence[str] | None = None,
        scope: str | None = None,
        role: str | None = "current",
        durations: Sequence[str] | None = None,
        latest_only: bool = True,
        knowledge_cutoff: datetime | None = None,
    ) -> PITFrame:
        """Fundamental values disclosed on KAP up to as_of (knowledge time = disclosure_datetime).

        role="current" (default): each value as published in its own report; a later correction of that report is a
        newer version. role="prior": comparative columns of later reports (TMS 29 restated in later purchasing power).
        role=None: both. latest_only keeps the newest version <= as_of per (fiscal_period, duration, scope, metric)
        and adds n_versions; latest_only=False returns every version (report-level comparisons).
        start/end filter the disclosure date. Anything published after as_of is invisible.
        """
        a = require_as_of(as_of)
        s, e, warnings = self._clamp(start, end, a)
        assert e is not None
        bound = knowledge_bound(a, knowledge_cutoff)
        params: list[Any] = [ticker, f"{fmt_date(e)} 23:59:59", bound]
        sql = (
            f"SELECT {self._FUND_COLS} FROM fundamentals "
            "WHERE ticker = ? AND disclosure_datetime <= ? AND disclosure_datetime <= ?"
        )
        if s is not None:
            sql += " AND disclosure_datetime >= ?"
            params.append(f"{fmt_date(s)} 00:00:00")
        for column, wanted in (("metric", metrics), ("duration", durations)):
            if wanted:
                sql += f" AND {column} IN ({_placeholders(len(wanted))})"
                params.extend(wanted)
        for column, value in (("scope", scope), ("role", role)):
            if value:
                sql += f" AND {column} = ?"
                params.append(value)
        df = self._read(sql + " ORDER BY disclosure_datetime, disclosure_index", params)
        self._post_check(df, "disclosure_datetime", bound, "fundamentals")
        if not df.empty and latest_only:
            keys = ["fiscal_period", "duration", "scope", "metric"]
            df["n_versions"] = df.groupby(keys)["value"].transform("size")
            # tail(1), not last(): last() would skip a NaN restatement and resurrect the old value
            df = (
                df.sort_values(["disclosure_datetime", "disclosure_index"], kind="stable")
                .groupby(keys)
                .tail(1)
                .sort_values(["period_end", "duration", "metric"], kind="stable")
                .reset_index(drop=True)
            )
        return PITFrame(data=df, as_of=a, start=s, end=e, warnings=warnings)

    def fundamental_reports(self, ticker: str, *, as_of: Any, scope: str | None = None) -> pd.DataFrame:
        """One row per KAP financial report of `ticker` published up to as_of (corrections are separate rows)."""
        a = require_as_of(as_of)
        bound = as_of_end_of_day(a)
        sql = (
            "SELECT disclosure_index, disclosure_datetime, report_period, scope, MAX(period_end) AS period_end, "
            "MAX(tms29_adjusted) AS tms29_adjusted, COUNT(*) AS n_values FROM fundamentals "
            "WHERE ticker = ? AND disclosure_datetime <= ? AND role = 'current'"
        )
        params: list[Any] = [ticker, bound]
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        df = self._read(sql + " GROUP BY disclosure_index ORDER BY disclosure_datetime, disclosure_index", params)
        self._post_check(df, "disclosure_datetime", bound, "fundamental_reports")
        return df

    def fundamental_issues(self, ticker: str, *, as_of: Any) -> pd.DataFrame:
        """Ingest issues (unit, column repair, conflicts) of reports published up to as_of."""
        a = require_as_of(as_of)
        bound = as_of_end_of_day(a)
        df = self._read(
            "SELECT ticker, disclosure_index, disclosure_datetime, code, severity, detail FROM fundamental_issues "
            "WHERE ticker = ? AND disclosure_datetime <= ? ORDER BY disclosure_datetime, disclosure_index",
            [ticker, bound],
        )
        self._post_check(df, "disclosure_datetime", bound, "fundamental_issues")
        return df

    def meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    # ------------------------------------------------------------------ macro
    def macro(
        self,
        series_codes: Sequence[str] | str,
        start: Any = None,
        end: Any = None,
        *,
        as_of: Any,
        knowledge_cutoff: datetime | None = None,
    ) -> PITFrame:
        """Latest released value (<= as_of) per (series, observation date). start/end filter obs_date."""
        a = require_as_of(as_of)
        codes = [series_codes] if isinstance(series_codes, str) else list(series_codes)
        s, e, warnings = self._clamp(start, end, a)
        assert e is not None
        bound = knowledge_bound(a, knowledge_cutoff)
        params: list[Any] = [*codes, fmt_date(e), bound]
        sql = (
            "SELECT series_code, obs_date, value, release_datetime, source, source_ref FROM macro_observations "
            f"WHERE series_code IN ({_placeholders(len(codes))}) AND obs_date <= ? AND release_datetime <= ?"
        )
        if s is not None:
            sql += " AND obs_date >= ?"
            params.append(fmt_date(s))
        df = self._read(sql + " ORDER BY release_datetime", params)
        self._post_check(df, "release_datetime", bound, "macro_observations")
        if not df.empty:
            df = (
                df.sort_values("release_datetime", kind="stable")
                .groupby(["series_code", "obs_date"])
                .tail(1)
                .sort_values(["series_code", "obs_date"], kind="stable")
                .reset_index(drop=True)
            )
        return PITFrame(data=df, as_of=a, start=s, end=e, warnings=warnings)

    # ------------------------------------------------------------------ news
    def news(
        self,
        start: Any = None,
        end: Any = None,
        *,
        as_of: Any,
        ticker: str | None = None,
        topic: str | None = None,
    ) -> PITFrame:
        a = require_as_of(as_of)
        s, e, warnings = self._clamp(start, end, a)
        assert e is not None
        bound = as_of_end_of_day(a)
        params: list[Any] = [f"{fmt_date(e)} 23:59:59", bound]
        sql = (
            "SELECT event_id, published_at, first_published_at, source, title, url, tickers, topics, event_type "
            "FROM news_events "
            "WHERE published_at <= ? AND published_at <= ?"
        )
        if s is not None:
            sql += " AND published_at >= ?"
            params.append(f"{fmt_date(s)} 00:00:00")
        if ticker:
            sql += " AND tickers LIKE ?"
            params.append(f'%"{ticker}"%')
        if topic:
            sql += " AND topics LIKE ?"
            params.append(f'%"{topic}"%')
        df = self._read(sql + " ORDER BY published_at", params)
        self._post_check(df, "published_at", bound, "news_events")
        return PITFrame(data=df, as_of=a, start=s, end=e, warnings=warnings)

    # ------------------------------------------------------------------ speech
    def _has_speech_claims(self) -> bool:
        return (
            self._conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'speech_claims'").fetchone()
            is not None
        )

    def speech_segments(
        self,
        *,
        as_of: Any,
        source_id: str | None = None,
        topic: str | None = None,
        include_claim_subject: bool = False,
    ) -> PITFrame:
        """Transcribed video segments published up to as_of (knowledge time = video publication time)."""
        a = require_as_of(as_of)
        bound = as_of_end_of_day(a)
        sql = (
            "SELECT source_id, segment_start, segment_end, published_at, url, speaker, channel, text, topics, stance, "
            "quality FROM speech_segments WHERE published_at <= ?"
        )
        params: list[Any] = [bound]
        if source_id:
            sql += " AND source_id = ?"
            params.append(source_id)
        if topic:
            sql += " AND (topics LIKE ?"
            params.append(f'%"{topic}"%')
            if include_claim_subject and self._has_speech_claims():
                sql += (
                    " OR EXISTS (SELECT 1 FROM speech_claims AS c WHERE c.source_id = speech_segments.source_id "
                    "AND c.segment_start = speech_segments.segment_start AND c.subject = ? AND c.published_at <= ?)"
                )
                params.extend((topic, bound))
            sql += ")"
        df = self._read(sql + " ORDER BY published_at, source_id, segment_start", params)
        self._post_check(df, "published_at", bound, "speech_segments")
        return PITFrame(data=df, as_of=a, start=None, end=a)

    def speech_claims(self, *, as_of: Any, source_id: str | None = None) -> PITFrame:
        """Return human-approved records using the source video's publication date."""
        a = require_as_of(as_of)
        bound = as_of_end_of_day(a)
        columns = (
            "claim_id, source_id, segment_start, published_at, subject, claim_type, quote, "
            "quoted_numbers, metric, direction, horizon_days, stance, certainty, review_note"
        )
        if not self._has_speech_claims():
            return PITFrame(data=pd.DataFrame(columns=columns.split(", ")), as_of=a, start=None, end=a)
        sql = f"SELECT {columns} FROM speech_claims WHERE published_at <= ?"
        params: list[Any] = [bound]
        if source_id is not None:
            sql += " AND source_id = ?"
            params.append(source_id)
        data = self._read(sql + " ORDER BY published_at, source_id, segment_start, claim_id", params)
        self._post_check(data, "published_at", bound, "speech_claims")
        return PITFrame(data=data, as_of=a, start=None, end=a)
