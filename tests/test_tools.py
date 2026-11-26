"""The 15 tools on a synthetic snapshot: contract, determinism, the PIT poison test for EVERY tool (CLAUDE.md §2),
evidence/number invariants, the risk gate rules, the evidence bundle and the MCP server."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from datetime import date
from typing import Any

import pandas as pd
import pytest
import yaml

from bistharness.core import formatting as fmt
from bistharness.core.config import load_settings, load_universe, project_root
from bistharness.core.errors import AsOfRequiredError
from bistharness.core.pit import PITRepository
from bistharness.core.schemas import ToolEnvelope
from bistharness.data import db
from bistharness.tools import REGISTRY, TOOL_NAMES, ToolContext, ToolInputError, run_tool
from bistharness.tools.context import NEWS_TOPICS
from bistharness.tools.quality import _future_dates
from tests.fixtures.synthetic_market import synthetic_ohlcv
from tests.test_fundamentals_analytics import ROWS, _rows
from tests.test_macro_stats import _rows as macro_rows

AS_OF = date(2026, 9, 10)
A = AS_OF.isoformat()
TICKERS = ["ASELS", "KATMR", "THYAO", "PGSUS", "BIMAS", "MGROS", "MAVI", "SOKM", "TUPRS", "PETKM", "XU100"]
FUND_COLS = [
    "ticker",
    "fiscal_period",
    "period_start",
    "period_end",
    "duration",
    "report_period",
    "role",
    "disclosure_datetime",
    "disclosure_index",
    "scope",
    "statement",
    "metric",
    "value",
    "unit",
    "tms29_adjusted",
    "source",
    "source_ref",
    "ingest_id",
]


def _insert_fund(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    df = df.assign(ticker="TUPRS", ingest_id="t")[FUND_COLS]
    conn.executemany(
        f"INSERT INTO fundamentals ({','.join(FUND_COLS)}) VALUES ({','.join('?' * len(FUND_COLS))})",
        df.astype(object).where(df.notna(), None).itertuples(index=False, name=None),
    )


def build(conn: sqlite3.Connection, *, poison: bool) -> None:
    db.init_db(conn)
    for i, t in enumerate(TICKERS):
        df = synthetic_ohlcv(1000, seed=100 + i)  # 2023-01-02 .. 2026-10-30
        keep = df if poison else df[df.index <= pd.Timestamp(AS_OF)]
        factor = 0.5 if poison and t == "ASELS" else 1.0  # a later split re-bases the whole factor history
        rows = []
        for d, r in keep.iterrows():
            future = d > pd.Timestamp(AS_OF)
            m = 100.0 if future else 1.0
            rows.append(
                (
                    t,
                    d.date().isoformat(),
                    r.open * m,
                    r.high * m,
                    r.low * m,
                    r.close * m,
                    r.volume,
                    1.0 if future else factor,
                    "synthetic",
                    "synthetic",
                    "t",
                )
            )
        conn.executemany("INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.executemany(
            "INSERT OR IGNORE INTO trading_calendar VALUES (?,?,?)", [(r[1], "synthetic", None) for r in rows]
        )
    conn.execute("INSERT INTO price_quality_flags VALUES ('ASELS', '2025-03-03', 'SUSPICIOUS_JUMP', 'soft', 'x', 't')")
    _insert_fund(conn, ROWS)
    macro = macro_rows()
    news = [
        ("n1", "2026-08-05 10:00:00", "THYAO", "regulation"),
        ("n2", "2026-08-20 12:00:00", "THYAO", "earnings"),
        ("n3", "2026-09-09 09:00:00", "THYAO", "fx"),
        ("n4", "2026-09-01 09:00:00", "TUPRS", "earnings"),
    ]
    if poison:
        conn.execute(
            "INSERT INTO price_quality_flags VALUES ('ASELS', '2026-09-20', 'BROKEN_PRICE_SERIES', 'hard', 'x', 't')"
        )
        _insert_fund(
            conn,
            pd.DataFrame(_rows("2026Q3", 90, "2026-11-01 18:30:00", {("2026Q2", "6M"): {"revenue": 1e15}}, {})).assign(
                report_period="2026Q3", fiscal_period="2026Q3"
            ),
        )
        _insert_fund(
            conn, pd.DataFrame(_rows("2026Q2", 91, "2026-09-20 09:00:00", {("2026Q2", "6M"): {"revenue": -1.0}}, {}))
        )
        extra = pd.DataFrame(
            [
                ("USDTRY", "2026-09-11", 999.0, "2026-09-11 15:30:00"),
                ("TCMB_POLICY_RATE", "2026-09-11", 99.0, "2026-09-11 00:00:00"),
                ("TUFE_YOY", "2026-09-01", 999.0, "2026-10-05 10:00:00"),
            ],
            columns=macro.columns,
        )
        macro = pd.concat([macro, extra])
        news += [("n9", "2026-09-11 08:00:00", "THYAO", "regulation")]
    conn.executemany(
        "INSERT INTO macro_observations VALUES (?,?,?,?,?,?,?)",
        [(*r, "synthetic", None, "t") for r in macro.itertuples(index=False, name=None)],
    )
    conn.executemany(
        "INSERT INTO news_events (event_id, published_at, first_published_at, source, title, url, tickers, topics, "
        "event_type, ingest_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                i,
                p,
                p,
                "synthetic",
                f"başlık {i} yüzde 12,5",
                f"https://example.org/{i}",
                json.dumps([t]),
                json.dumps([tp]),
                tp,
                "t",
            )
            for i, p, t, tp in news
        ],
    )
    conn.execute("INSERT INTO meta VALUES ('fundamentals_coverage_end', '2026-10-02 19:56:09')")
    conn.commit()


def _ctx(poison: bool) -> ToolContext:
    conn = sqlite3.connect(":memory:", check_same_thread=False)  # the MCP server runs tools in worker threads
    build(conn, poison=poison)
    return ToolContext(PITRepository(conn), load_settings(), load_universe())


@pytest.fixture(scope="module")
def clean() -> Iterator[ToolContext]:
    yield _ctx(False)


@pytest.fixture(scope="module")
def poisoned() -> Iterator[ToolContext]:
    yield _ctx(True)


CALLS: list[tuple[str, dict[str, Any]]] = [
    ("get_stock_history", {"ticker": "ASELS", "start": "2025-01-01"}),
    ("get_index_history", {"start": "2025-01-01"}),
    ("calculate_indicators", {"ticker": "ASELS", "tail": 3}),
    ("detect_reversal_events", {"ticker": "ASELS", "start": "2025-01-01"}),
    ("find_support_resistance", {"ticker": "ASELS"}),
    ("rank_sector_relative_strength", {"sector_or_tickers": "BIMAS"}),
    ("test_weekday_pattern", {"ticker": "THYAO"}),
    ("get_fundamental_metrics", {"ticker": "TUPRS"}),
    ("calculate_fundamental_change", {"ticker": "TUPRS"}),
    ("get_macro_context", {"start": "2025-06-01", "ticker_for_corr": "THYAO"}),
    ("get_news_events", {"ticker_or_topic": "THYAO", "start": "2026-08-01"}),
    ("get_speech_features", {"source_id_or_topic": "rates"}),
    ("run_backtest", {"universe": ["ASELS", "BIMAS", "TUPRS"], "start": "2025-01-01", "split_date": "2026-01-01"}),
]


@pytest.fixture(scope="module")
def clean_envs(clean: ToolContext) -> dict[str, ToolEnvelope]:
    return {name: run_tool(name, {**args, "as_of_date": A}, clean) for name, args in CALLS}


def test_registry_has_the_15_tools_with_mandatory_as_of() -> None:
    assert set(TOOL_NAMES) == set(REGISTRY) and len(TOOL_NAMES) == 15
    for td in REGISTRY.values():
        assert td.input_model.model_fields["as_of_date"].is_required() and td.description


def test_invalid_calls(clean: ToolContext) -> None:
    with pytest.raises(AsOfRequiredError):
        run_tool("get_stock_history", {"ticker": "ASELS"}, clean)
    with pytest.raises(ToolInputError, match="invalid input"):
        run_tool("get_stock_history", {"ticker": "ASELS", "as_of_date": A, "foo": 1}, clean)
    with pytest.raises(ToolInputError, match="unknown ticker"):
        run_tool("calculate_indicators", {"ticker": "NOPE", "as_of_date": A}, clean)
    with pytest.raises(ToolInputError, match="unknown tool"):
        run_tool("buy_stock", {"as_of_date": A}, clean)


@pytest.mark.parametrize(("name", "args"), CALLS, ids=[c[0] for c in CALLS])
def test_tool_is_deterministic_and_poison_proof(
    name: str, args: dict[str, Any], clean_envs: dict[str, ToolEnvelope], poisoned: ToolContext
) -> None:
    env = clean_envs[name]
    assert env.status.value != "ERROR"
    assert env.tool == name and env.as_of_date == AS_OF and env.call_id and env.output_hash
    bad = run_tool(name, {**args, "as_of_date": A}, poisoned)
    assert bad.call_id == env.call_id
    assert bad.output_hash == env.output_hash, f"{name}: output changed by rows published after as_of"
    assert (
        _future_dates(env.model_dump(mode="json", include={"result", "excluded_incomplete_events"}), f"{A} 23:59:59")
        == []
    )


@pytest.mark.parametrize("name", [c[0] for c in CALLS])
def test_every_number_in_a_claim_is_a_display_value(name: str, clean_envs: dict[str, ToolEnvelope]) -> None:
    for c in clean_envs[name].evidence_candidates:
        shown = {n for v in c.display.values() for n in fmt.numbers_in(v)}
        assert set(fmt.numbers_in(c.claim_tr)) <= shown, (c.key, c.claim_tr)
        assert set(fmt.dates_in(c.claim_tr)) <= {d for v in c.display.values() for d in fmt.dates_in(v)}


def test_news_numbers_never_reach_display(clean_envs: dict[str, ToolEnvelope]) -> None:
    env = clean_envs["get_news_events"]
    assert env.result["count"] == 3
    assert all("12,5" not in v for c in env.evidence_candidates for v in c.display.values())


def test_news_topics_match_config() -> None:
    with (project_root() / "config" / "news.yaml").open(encoding="utf-8") as fh:
        assert tuple(yaml.safe_load(fh)["topics"]) == NEWS_TOPICS


def test_speech_without_segments_is_a_soft_warning(clean_envs: dict[str, ToolEnvelope]) -> None:
    # missing speech context must not escalate the risk gate to INVESTIGATE (CLAUDE.md §4)
    env = clean_envs["get_speech_features"]
    assert env.status.value == "OK_WITH_WARNINGS" and env.warnings[0].code.value == "SPEECH_NOT_AVAILABLE"
    assert env.warnings[0].severity.value == "soft"


def test_missing_peers_are_warned_not_fatal(clean_envs: dict[str, ToolEnvelope]) -> None:
    env = clean_envs["calculate_fundamental_change"]
    missing = {w.ticker for w in env.warnings if w.code.value == "PRICE_MISSING"}
    assert {"SASA", "AKSA", "KORDS"} <= missing and env.result["peers"] == ["PETKM"]


def _gate(
    ctx: ToolContext,
    envs: list[dict[str, Any]],
    committed: list[str] | None = None,
    tickers: list[str] | None = None,
    as_of: str = A,
) -> dict[str, Any]:
    bundle = {"tickers": tickers or [], "envelopes": envs, "committed_keys": committed}
    return run_tool("check_data_quality", {"as_of_date": as_of, "analysis_bundle": bundle}, ctx).result


def test_gate_rules(clean: ToolContext, clean_envs: dict[str, ToolEnvelope]) -> None:
    hist = clean_envs["get_stock_history"].model_dump(mode="json")
    ok = _gate(clean, [hist], tickers=["ASELS"])
    assert ok["gate"] == "PASS_WITH_WARNINGS"  # the soft SUSPICIOUS_JUMP flag in the window
    assert "TECHNICAL_REVERSAL_CANDIDATE" in ok["allowed_actions"]
    tampered = json.loads(json.dumps(hist))
    tampered["result"]["period_return"] = 9.99
    assert _gate(clean, [tampered])["gate"] == "HARD_BLOCK"
    future = json.loads(json.dumps(hist))
    future["result"]["last_date"] = "2026-09-11"
    future = ToolEnvelope.model_validate(future).finalize().model_dump(mode="json")  # re-hashed: only the date leaks
    assert _gate(clean, [future])["gate"] == "HARD_BLOCK"
    assert _gate(clean, [hist], as_of="2026-09-11")["gate"] == "HARD_BLOCK"  # envelope for another as_of
    assert _gate(clean, [hist], committed=["made.up.key"])["gate"] == "ANALYSIS_UNSAFE"
    rev = clean_envs["detect_reversal_events"]
    tiny = [
        c.key
        for c in rev.evidence_candidates
        if c.kind == "statistic" and isinstance(c.values.get("n"), int) and c.values["n"] < 5
    ]
    res = _gate(clean, [rev.model_dump(mode="json")], committed=tiny[:1])
    assert tiny and res["gate"] == "INVESTIGATE"
    assert set(res["allowed_actions"]) == {"INVESTIGATE", "WATCH", "REJECT_SIGNAL", "ANALYSIS_UNSAFE"}
    speech = clean_envs["get_speech_features"].model_dump(mode="json")
    assert _gate(clean, [speech])["gate"] == "PASS_WITH_WARNINGS"  # missing speech context is a soft warning
    starved = json.loads(json.dumps(speech))
    starved["status"] = "INSUFFICIENT_DATA"
    starved = ToolEnvelope.model_validate(starved).finalize().model_dump(mode="json")
    assert _gate(clean, [starved])["gate"] == "INVESTIGATE"  # any tool reporting INSUFFICIENT_DATA still escalates


def test_evidence_bundle(clean: ToolContext, clean_envs: dict[str, ToolEnvelope]) -> None:
    envs = [clean_envs[n].model_dump(mode="json") for n in ("calculate_indicators", "detect_reversal_events")]
    b1 = run_tool(
        "build_evidence_bundle", {"as_of_date": A, "analysis_id": "t1", "observed_context": envs}, clean
    ).result
    b2 = run_tool(
        "build_evidence_bundle", {"as_of_date": A, "analysis_id": "t1", "observed_context": envs}, clean
    ).result
    assert b1 == b2 and [c["id"] for c in b1["committed"]] == [f"E{i + 1}" for i in range(len(b1["committed"]))]
    assert len(b1["committed"]) <= 12 and all(c["primary"] for c in b1["committed"])
    for c in b1["committed"]:
        assert set(fmt.numbers_in(c["claim_tr"])) <= set(b1["allowed_numbers"])
    key = clean_envs["calculate_indicators"].evidence_candidates[0].key
    pick = run_tool(
        "build_evidence_bundle",
        {"as_of_date": A, "analysis_id": "t2", "observed_context": envs, "commit_keys": [key]},
        clean,
    ).result
    assert [c["key"] for c in pick["committed"]] == [key]
    envs[0]["result"]["values"]["rsi"] = 1.0
    with pytest.raises(ToolInputError, match="output hash"):
        run_tool("build_evidence_bundle", {"as_of_date": A, "analysis_id": "t3", "observed_context": envs}, clean)


def test_mcp_server_exposes_and_runs_the_tools(clean: ToolContext) -> None:
    from bistharness.mcp_server.server import build_server

    server = build_server(clean)
    tools = asyncio.run(server.list_tools())
    assert sorted(t.name for t in tools) == sorted(TOOL_NAMES)
    schema = next(t for t in tools if t.name == "get_stock_history").input_schema
    assert "as_of_date" in schema["required"] and "ticker" in schema["properties"]
    out = asyncio.run(server.call_tool("get_index_history", {"as_of_date": A, "start": "2026-01-01"}))
    payload = out.structured_content if getattr(out, "structured_content", None) else json.loads(out.content[0].text)
    payload = payload.get("result", payload) if "tool" not in payload else payload
    assert payload["tool"] == "get_index_history" and payload["as_of_date"] == A
    err = asyncio.run(server.call_tool("get_stock_history", {"as_of_date": A, "ticker": "NOPE"}))
    err_payload = (
        err.structured_content if getattr(err, "structured_content", None) else json.loads(err.content[0].text)
    )
    err_payload = err_payload.get("result", err_payload) if "status" not in err_payload else err_payload
    assert err_payload["status"] == "ERROR"
