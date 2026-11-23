"""PIT poison test for the whole analytics layer (CLAUDE.md §2): absurd rows published after as_of — prices, a later
split re-basing every factor, a future report, a correction, a macro release — must not change any output read
through PITRepository."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from bistharness.analytics import event_study, events, indicators, macro_stats, regimes, sector, series, weekday
from bistharness.analytics import fundamentals as fa
from bistharness.core.enums import FundamentalTemplate
from bistharness.core.pit import PITRepository
from tests.conftest import insert_prices
from tests.fixtures.synthetic_market import synthetic_closes
from tests.test_fundamentals_analytics import ROWS, _rows

AS_OF = date(2024, 7, 31)
FUND_COLS = (
    "ticker, fiscal_period, period_start, period_end, duration, report_period, role, disclosure_datetime, "
    "disclosure_index, scope, statement, metric, value, unit, tms29_adjusted, source, source_ref, ingest_id"
)
CLOSES = synthetic_closes(["AAA", "BBB", "CCC", "XU100"], n=420, seed=21)  # 2023-01-02 .. 2024-08-14


def _shift_years(df: pd.DataFrame, years: int) -> pd.DataFrame:
    """Move the synthetic KAP rows two years back so they sit inside the synthetic price history."""
    out = df.copy()
    for c in ("fiscal_period", "report_period"):
        out[c] = [f"{int(v[:4]) - years}{v[4:]}" for v in out[c]]
    for c in ("period_end", "disclosure_datetime"):
        out[c] = [f"{int(v[:4]) - years}{v[4:]}" for v in out[c]]
    return out


FUND = _shift_years(ROWS, 2)


def _insert_fund(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    cols = [c.strip() for c in FUND_COLS.split(",")]
    df = df.assign(ingest_id="t")[cols]
    conn.executemany(
        f"INSERT INTO fundamentals ({FUND_COLS}) VALUES ({','.join('?' * len(cols))})",
        df.astype(object).where(df.notna(), None).itertuples(index=False, name=None),
    )


def _build(conn: sqlite3.Connection, *, poison: bool) -> None:
    past = CLOSES[CLOSES.index <= pd.Timestamp(AS_OF)]
    factor = 0.1 if poison else 1.0  # a later split re-bases every historical factor by a constant
    for t in CLOSES.columns:
        insert_prices(conn, t, [d.date() for d in past.index], list(past[t]), factors=[factor] * len(past))
    _insert_fund(conn, FUND)
    macro = [
        ("TCMB_POLICY_RATE", "2024-03-22", 50.0, "2024-03-22 00:00:00"),
        ("USDTRY", "2024-07-31", 32.9, "2024-07-31 15:30:00"),
        ("TUFE_YOY", "2024-06-01", 71.6, "2024-07-03 10:00:00"),
        ("TUFE_MOM", "2024-06-01", 1.64, "2024-07-03 10:00:00"),
    ]
    if poison:
        future = CLOSES[CLOSES.index > pd.Timestamp(AS_OF)]
        for t in CLOSES.columns:
            insert_prices(conn, t, [d.date() for d in future.index], [1e6] * len(future))
        conn.execute(
            "INSERT INTO corporate_actions VALUES ('AAA', ?, 10.0, 'split_or_bonus', 'synthetic', NULL, 't')",
            (future.index[0].date().isoformat(),),
        )
        late = pd.DataFrame(
            _rows("2026Q3", 99, "2026-11-01 18:30:00", {("2026Q2", "6M"): {"revenue": 1e12}}, {})
        )  # 2024Q3 report, after as_of
        late["period_end"] = "2026-09-30"
        _insert_fund(conn, _shift_years(late, 2))
        corr = pd.DataFrame(_rows("2026Q1", 98, "2026-08-20 09:00:00", {("2026Q1", "3M"): {"revenue": -5.0}}, {}))
        _insert_fund(conn, _shift_years(corr, 2))  # correction of the 2024Q1 report, published after as_of
        macro += [
            ("TCMB_POLICY_RATE", "2024-07-31", 99.0, "2024-08-01 00:00:00"),
            ("TUFE_YOY", "2024-07-01", 999.0, "2024-08-05 10:00:00"),
        ]
    conn.executemany(
        "INSERT INTO macro_observations VALUES (?,?,?,?,?,?,?)", [(*m, "synthetic", None, "t") for m in macro]
    )
    conn.commit()


def _plain(x: Any) -> Any:
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: _plain(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, pd.DataFrame):
        return _plain(x.to_dict("list"))
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_plain(v) for v in x]
    if hasattr(x, "model_dump"):
        return x.model_dump()
    if isinstance(x, float) and np.isnan(x):
        return "nan"
    return x


def _pipeline(repo: PITRepository) -> dict[str, Any]:
    cal = repo.trading_calendar(as_of=AS_OF)
    px = repo.prices(list(CLOSES.columns), as_of=AS_OF).data
    a, xu = series.ohlcv(px, "AAA"), series.ohlcv(px, "XU100")["close"]
    ind = indicators.compute_indicators(a)
    flags, state = events.detect_events(ind), events.market_state(ind)
    study = event_study.reversal_event_study(
        ind, flags, state, cal, ticker="AAA", start=date(2024, 1, 1), benchmark=xu, regimes=regimes.market_regimes(xu)
    )
    group = series.column_matrix(px, ["AAA", "BBB", "CCC"])
    snap = sector.sector_snapshot(group, group="G", calendar=cal, benchmark=xu)
    catch = sector.catch_up_study({"G": group}, cal, start=date(2023, 6, 1), benchmark=xu)
    ret = weekday.daily_returns(a["close"])
    pat = weekday.WeekdayPattern((("Mon", -1), ("Tue", -1)), ("Thu", "Fri"))
    wd = weekday.evaluate_weekday_pattern(ret, pat, periods={"all": (date(2023, 1, 1), AS_OF)}, as_of=AS_OF)
    reps = fa.build_reports(repo.fundamentals("SYN", as_of=AS_OF, role=None, latest_only=False).data, ticker="SYN")
    latest = reps[max(reps)]
    rm = fa.report_metrics(latest, reps, template=FundamentalTemplate.INDUSTRIAL, tms29_applies=True)
    reac = fa.post_disclosure_reactions(list(reps.values()), a["close"], cal, benchmark=xu)
    macro = macro_stats.macro_snapshot(
        repo.macro(["TCMB_POLICY_RATE", "USDTRY", "TUFE_YOY", "TUFE_MOM"], as_of=AS_OF).data, AS_OF
    )
    return _plain(
        {
            "study": study.studies,
            "records": study.records,
            "snap": snap.rows,
            "catch": catch.horizons,
            "catch_excluded": catch.excluded,
            "weekday": [(p.conditional, p.p_bh, p.complete_weeks) for p in wd.periods],
            "reports": sorted(reps),
            "metrics": rm.levels,
            "ratios": rm.ratios,
            "reactions": reac.table,
            "reaction_excluded": reac.excluded,
            "macro": macro.latest,
            "ind_tail": ind.tail(5),
        }
    )


def test_future_rows_change_nothing(mem_conn: sqlite3.Connection) -> None:
    _build(mem_conn, poison=False)
    clean = _pipeline(PITRepository(mem_conn))
    poisoned_conn = sqlite3.connect(":memory:")
    from bistharness.data import db

    db.init_db(poisoned_conn)
    _build(poisoned_conn, poison=True)
    repo = PITRepository(poisoned_conn)
    poisoned = _pipeline(repo)
    # the clean run is not vacuous ...
    assert clean["reports"][-1] == "2024Q1"  # the 2024Q2 report (2024-08-04) is after as_of
    assert sum(s["n_events"] for s in clean["study"]) > 0 and clean["reactions"]["ret"]
    assert clean["macro"]["TCMB_POLICY_RATE"]["value"] == 50.0
    # ... and the poison is real: it is visible to a later as_of
    later = repo.fundamentals("SYN", as_of="2024-12-31", role=None, latest_only=False).data
    assert {"2024Q2", "2024Q3"} <= set(later["report_period"]) and (later["value"] == -5.0).any()
    assert repo.prices("AAA", as_of="2024-08-14").data["raw_close"].max() == 1e6
    poisoned_conn.close()
    assert clean == poisoned
