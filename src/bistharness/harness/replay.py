"""replay_analysis(decision_id) (CLAUDE.md §8): re-run every logged tool call with the same inputs on the current
snapshot and compare hashes; optionally re-run the explanation prompt with the same model/seed and compare the raw
LLM output.

Calls that embedded other envelopes (evidence bundle, risk gate) are rebuilt from the replayed envelopes (stored rows
keep only their call ids) and compared on their result hash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from bistharness.core.enums import ALLOWED_ACTIONS_BY_GATE, GateStatus
from bistharness.core.hashing import sha256_hex
from bistharness.harness.llm_client import LLMClient
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.validator import output_schema
from bistharness.tools import ToolContext, run_tool


@dataclass
class CallReplay:
    seq: int
    tool: str
    state: str
    match: bool
    stored_hash: str
    replay_hash: str
    basis: str  # output_hash | result_hash


@dataclass
class ReplayReport:
    decision_id: str
    analysis_id: str
    data_version_match: bool
    calls: list[CallReplay] = field(default_factory=list)
    llm_compared: bool = False
    llm_match: bool | None = None
    llm_diff: str | None = None

    @property
    def tools_match(self) -> bool:
        return all(c.match for c in self.calls)


def _expand(inputs: dict[str, Any], by_call: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = dict(inputs)
    if "observed_context" in out:
        out["observed_context"] = [by_call[e["call_id"]] for e in out["observed_context"]]
    if isinstance(out.get("analysis_bundle"), dict):
        b = dict(out["analysis_bundle"])
        b["envelopes"] = [by_call[e["call_id"]] for e in b.get("envelopes", [])]
        out["analysis_bundle"] = b
    return out


def replay_analysis(
    decision_id: str, ctx: ToolContext, memory: EpisodicMemory, client: LLMClient | None = None
) -> ReplayReport:
    dec = memory.decision(decision_id)
    if dec is None:
        raise KeyError(f"unknown decision {decision_id}")
    aid = dec["analysis_id"]
    an = memory.analysis(aid)
    assert an is not None
    report = ReplayReport(decision_id, aid, json.loads(an["data_version"]) == ctx.data_version)
    by_call: dict[str, dict[str, Any]] = {}  # stored call_id -> replayed envelope JSON
    for row in memory.tool_calls(aid):
        if not row["valid"]:
            continue
        stored = json.loads(row["envelope_json"])
        light = bool(stored.get("inputs_lightened"))
        inputs = _expand(stored["inputs"], by_call) if light else stored["inputs"]
        env = run_tool(row["tool"], inputs, ctx).model_dump(mode="json")
        by_call[row["call_id"]] = env
        if light:
            a, b = sha256_hex(stored["result"]), sha256_hex(env["result"])
            if row["tool"] == "build_evidence_bundle":  # its bundle_id/analysis_id are run-specific: compare content
                a = sha256_hex({k: v for k, v in stored["result"].items() if k not in ("tools", "bundle_id")})
                b = sha256_hex({k: v for k, v in env["result"].items() if k not in ("tools", "bundle_id")})
            report.calls.append(CallReplay(row["seq"], row["tool"], row["state"], a == b, a, b, "result_hash"))
        else:
            report.calls.append(
                CallReplay(
                    row["seq"],
                    row["tool"],
                    row["state"],
                    env["output_hash"] == stored["output_hash"],
                    stored["output_hash"],
                    env["output_hash"],
                    "output_hash",
                )
            )
    if client is not None:
        llm = [r for r in memory.llm_calls(aid) if r["purpose"] == "explanation"]
        if llm:
            first = llm[0]
            msgs = json.loads(first["messages_json"])
            allowed = sorted(a.value for a in ALLOWED_ACTIONS_BY_GATE[GateStatus(dec["gate"])])
            schema = output_schema(allowed)  # the same schema the explanation was generated with
            resp = client.chat(msgs, schema)
            report.llm_compared = True
            report.llm_match = resp.text == first["raw_output"]
            if not report.llm_match:
                report.llm_diff = f"stored={first['raw_output'][:300]!r} replay={resp.text[:300]!r}"
    return report
