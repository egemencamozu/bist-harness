"""A–E ablation helpers (eval/ablation.py): the shared audit and the evidence cap, without any LLM."""

from __future__ import annotations

import json
from datetime import date

from bistharness.core.enums import GateStatus, Scenario
from bistharness.harness.policy import load_policy
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.validator import output_schema
from eval import ablation

POLICY = load_policy()
REQ = AnalysisRequest(
    question="ASELS'te son 20 günde RSI dibi sonrası ne oldu?",
    scenario=Scenario.S3_TECHNICAL_REVERSAL,
    tickers=["ASELS"],
    as_of_date=date(2026, 4, 17),
)
EV = [
    {
        "id": "E1",
        "key": "k1",
        "claim_tr": "RSI dibi 12 kez oluştu; 8 tanesinde yükseliş (%66,67).",
        "display": {},
        "kind": "statistic",
    },
]


def _ans(text: str, action: str = "WATCH", cited: list[str] | None = None, refusal: bool = False) -> str:
    return json.dumps(
        {
            "action": action,
            "explanation_tr": text,
            "cited_evidence": cited if cited is not None else ["E1"],
            "refusal_needed": refusal,
            "limitations_tr": "",
        },
        ensure_ascii=False,
    )


def test_audit_counts_numbers_the_model_was_not_shown() -> None:
    ok = ablation.audit(_ans("RSI dibi 12 kez oluştu, %66,67 yükseliş (E1)."), EV, REQ, GateStatus.PASS, POLICY)
    assert not ok["rule_violation"] and ok["invented_numbers"] == 0 and not ok["unsupported_conclusion"]
    # level A sees no evidence: the same sentence is invented, the citation does not exist
    a = ablation.audit(_ans("RSI dibi 12 kez oluştu, %66,67 yükseliş (E1)."), [], REQ, GateStatus.PASS, POLICY)
    assert a["invented_numbers"] == 2 and a["unsupported_conclusion"] and a["rule_violation"]
    # numbers quoted from the question (20 gün) are never "invented"
    q = ablation.audit(_ans("Son 20 günde dip oluştu (E1)."), EV, REQ, GateStatus.PASS, POLICY)
    assert q["invented_numbers"] == 0


def test_audit_uses_the_reference_gate_and_flags_broken_json() -> None:
    cand = _ans("Güncel teknik dönüş adayı görünüyor (E1).", action="TECHNICAL_REVERSAL_CANDIDATE")
    r = ablation.audit(cand, EV, REQ, GateStatus.INVESTIGATE, POLICY)
    assert r["action_violation"] and r["candidate_without_backtest"] and r["rule_violation"]
    broken = ablation.audit('{"action": "WATCH", "explanation_tr": "Kanıtlar', EV, REQ, GateStatus.PASS, POLICY)
    assert not broken["schema_ok"] and broken["rule_violation"]


def test_evidence_cap_keeps_primary_first_and_numbers_ids() -> None:
    from bistharness.core.schemas import EvidenceCandidate, ToolEnvelope

    def env(tool: str, keys: list[tuple[str, bool]]) -> ToolEnvelope:
        return ToolEnvelope.model_construct(
            tool=tool,
            evidence_candidates=[
                EvidenceCandidate.model_construct(key=k, claim_tr="x" * 1000, display={}, kind="statistic", primary=p)
                for k, p in keys
            ],
        )

    envs = [
        env("detect_reversal_events", [("a", False), ("b", True)]),
        env("check_data_quality", [("g", True)]),
        env("run_backtest", [("c", True), ("d", False)]),
    ]
    ev, cut = ablation.evidence_from(envs)
    assert [e["key"] for e in ev] == ["b", "c"] and [e["id"] for e in ev] == ["E1", "E2"]  # 3.000-char budget
    assert cut == 2  # a, d cut; the gate tool is level D's and never shown


def test_answer_schema_caps_stay_within_what_ollama_enforces() -> None:
    props = output_schema(["WATCH"])["properties"]
    assert props["explanation_tr"]["maxLength"] <= 2000 and props["limitations_tr"]["maxLength"] <= 2000
    assert props["cited_evidence"]["maxItems"] == 16
