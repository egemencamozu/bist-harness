"""The tools on the real frozen snapshot at the golden as_of (skipped when the DB is missing).

Pins what the five golden questions (CLAUDE.md §10) will read from the tools, and checks the evidence invariant
(every number of a claim is a display value) on real outputs.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from bistharness.core import formatting as fmt
from bistharness.core.config import load_settings
from bistharness.core.schemas import ToolEnvelope
from bistharness.tools import ToolContext, run_tool

DB = load_settings().db_path
pytestmark = [pytest.mark.data, pytest.mark.skipif(not DB.exists(), reason="snapshot DB not built")]
A = "2026-09-10"
CALLS: dict[str, tuple[str, dict[str, Any]]] = {
    "q1_sector": ("rank_sector_relative_strength", {"sector_or_tickers": ["BIMAS", "MGROS", "MAVI"]}),
    "q1_bimas": ("calculate_fundamental_change", {"ticker": "BIMAS"}),
    "q2": ("test_weekday_pattern", {"ticker": "THYAO"}),
    "q3": ("detect_reversal_events", {"ticker": "ASELS"}),
    "q4": ("calculate_fundamental_change", {"ticker": "TUPRS"}),
    "q4_metrics": ("get_fundamental_metrics", {"ticker": "TUPRS"}),
    "q5": ("get_macro_context", {"ticker_for_corr": "EREGL"}),
    "bank": ("get_fundamental_metrics", {"ticker": "AKBNK"}),
    "no_kap": ("get_fundamental_metrics", {"ticker": "TRALT"}),
}


@pytest.fixture(scope="module")
def envs() -> Iterator[dict[str, ToolEnvelope]]:
    ctx = ToolContext.from_settings()
    yield {k: run_tool(name, {**args, "as_of_date": A}, ctx) for k, (name, args) in CALLS.items()}


def _ev(env: ToolEnvelope, key: str) -> Any:
    return next(c for c in env.evidence_candidates if c.key == key)


def test_q1_retail_catch_up_inputs(envs: dict[str, ToolEnvelope]) -> None:
    sec = envs["q1_sector"]
    assert sec.result["members_with_data"] == ["BIMAS", "MGROS", "MAVI"] and sec.result["leaders"] == ["BIMAS"]
    assert [h["horizon"] for h in sec.result["catch_up"]["horizons"]] == [5, 10, 20]
    bimas = envs["q1_bimas"]
    assert [
        (e.event_date.isoformat(), e.horizon, e.trading_days_available) for e in bimas.excluded_incomplete_events
    ] == [("2026-08-17", 20, 18)]


def test_q2_thyao_weekday(envs: dict[str, ToolEnvelope]) -> None:
    p = envs["q2"].result["periods"]
    assert (p["in_sample"]["complete_weeks"], p["in_sample"]["condition_weeks"]) == (87, 19)
    assert (p["out_of_sample"]["complete_weeks"], p["out_of_sample"]["condition_weeks"]) == (29, 3)
    st = envs["q2"].result["stability"]
    assert st["out_of_sample_sufficient"] is False and st["same_sign_out_of_sample"] is False


def test_q3_asels_reversal(envs: dict[str, ToolEnvelope]) -> None:
    rows = {r["event_type"]: r for r in envs["q3"].result["summary"]}
    assert (rows["BB_LOWER_REVERSAL"]["n"], rows["BB_LOWER_REVERSAL"]["n_success"]) == (12, 8)
    assert rows["SUPERTREND_BULLISH_FLIP"]["n_events"] > 0  # the reference script finds none
    assert "BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE" in rows and "BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD" in rows
    last = max(e.event_date for e in envs["q3"].excluded_incomplete_events)
    assert last.isoformat() <= A and envs["q3"].result["family_size"] == 27


def test_q4_tuprs(envs: dict[str, ToolEnvelope]) -> None:
    rep = envs["q4"].result["reports"][-1]
    assert rep["fiscal_period"] == "2026Q2" and rep["timing"] == "after_close" and rep["base_day"] == "2026-08-04"
    assert set(rep["reaction"]) == {"1", "5", "20"} and envs["q4"].excluded_incomplete_events == []
    em = rep["ratio_changes"]["ebitda_margin"]
    assert em["new"] > em["old"]
    assert _ev(envs["q4_metrics"], "fundamentals.TUPRS.latest_report").display["dt"] == "04.08.2026 18:24"


def test_q5_eregl_fx(envs: dict[str, ToolEnvelope]) -> None:
    c = _ev(envs["q5"], "macro.EREGL.USDTRY.relationship")
    assert c.values["n"] == 140 and c.kind == "statistic"
    assert envs["q5"].result["latest"]["TCMB_POLICY_RATE"]["value"] == 37.0


def test_template_rules_and_missing_kap(envs: dict[str, ToolEnvelope]) -> None:
    assert envs["bank"].result["statement_format"] == "bank"
    assert envs["bank"].result["ratios"]["current_ratio"]["reason"] == "NOT_APPLICABLE_FOR_TEMPLATE"
    assert envs["no_kap"].status.value == "INSUFFICIENT_DATA"


def test_evidence_numbers_are_display_values_on_real_outputs(envs: dict[str, ToolEnvelope]) -> None:
    for env in envs.values():
        for c in env.evidence_candidates:
            shown = {n for v in c.display.values() for n in fmt.numbers_in(v)}
            assert set(fmt.numbers_in(c.claim_tr)) <= shown, (c.key, c.claim_tr)
