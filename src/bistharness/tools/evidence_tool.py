"""build_evidence_bundle — separates the Observed Context from the Committed Evidence Set (spec §25).

Observed context = every evidence candidate of every envelope, in the given (state) order, then by key.
Committed set = `commit_keys` if the harness passes them, otherwise the tools' primary candidates; at most
`max_committed`, warnings are always kept. IDs are deterministic: E1..En in committed order, O1..Om for the rest.
`allowed_numbers` are the numeric values written in the committed display strings — the ONLY numbers an explanation
may contain (validator, CLAUDE.md §4). Envelopes whose hash does not match their content are rejected.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, ValidationError, field_validator

from bistharness.core import formatting as fmt
from bistharness.core.hashing import sha256_hex
from bistharness.core.schemas import ToolEnvelope
from bistharness.tools.base import ToolContext, ToolInput, ToolInputError, ToolOutput, strip_wall_clock, tool


class EvidenceBundleInput(ToolInput):
    analysis_id: str = Field(min_length=1)
    observed_context: list[dict[str, Any]] = Field(default_factory=list)
    commit_keys: list[str] | None = None
    max_committed: int = Field(default=12, ge=1, le=40)

    @field_validator("observed_context")
    @classmethod
    def _no_wall_clock(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return strip_wall_clock(v)


@tool(
    "build_evidence_bundle",
    version="1.0.0",
    input_model=EvidenceBundleInput,
    sources=(),
    description="Builds the evidence bundle of an analysis: all observed evidence (O#) and the committed evidence "
    "set (E#) with the exact display strings and the numbers an explanation is allowed to quote.",
)
def build_evidence_bundle(ctx: ToolContext, inp: EvidenceBundleInput) -> ToolOutput:
    envs: list[ToolEnvelope] = []
    for i, raw in enumerate(inp.observed_context):
        try:
            env = ToolEnvelope.model_validate(raw)
        except ValidationError as exc:
            raise ToolInputError(f"observed_context[{i}] is not a tool envelope: {exc.error_count()} error(s)") from exc
        if env.finalize().output_hash != env.output_hash:
            raise ToolInputError(f"observed_context[{i}] ({env.tool}) does not match its output hash")
        if env.as_of_date != inp.as_of_date:
            raise ToolInputError(f"observed_context[{i}] ({env.tool}) was computed for as_of {env.as_of_date}")
        envs.append(env)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for env in envs:
        for c in env.evidence_candidates:
            if c.key in seen:
                continue
            seen.add(c.key)
            items.append(
                {
                    "key": c.key,
                    "tool": env.tool,
                    "call_id": env.call_id,
                    "claim_tr": c.claim_tr,
                    "display": c.display,
                    "values": c.values,
                    "json_pointer": c.json_pointer,
                    "kind": c.kind,
                    "primary": c.primary,
                }
            )
    by_key = {it["key"]: it for it in items}
    if inp.commit_keys is not None:
        missing = [k for k in inp.commit_keys if k not in by_key]
        if missing:
            raise ToolInputError(f"commit_keys not produced by any tool: {missing}")
        chosen = [by_key[k] for k in inp.commit_keys]
    else:
        chosen = [it for it in items if it["primary"]]
    if len(chosen) > inp.max_committed:
        warn_items = [it for it in chosen if it["kind"] == "warning"]
        others = [it for it in chosen if it["kind"] != "warning"][: max(0, inp.max_committed - len(warn_items))]
        keep = {it["key"] for it in warn_items + others}
        chosen = [it for it in chosen if it["key"] in keep]
    committed_keys = [it["key"] for it in chosen]
    committed = [{"id": f"E{i + 1}", **it} for i, it in enumerate(chosen)]
    observed = [
        {"id": f"O{i + 1}", **it} for i, it in enumerate(x for x in items if x["key"] not in set(committed_keys))
    ]
    displays = sorted({v for it in chosen for v in it["display"].values()} | {it["claim_tr"] for it in chosen})
    numbers = sorted({n for s in displays for n in fmt.numbers_in(s)})
    bundle_id = sha256_hex(
        {"analysis_id": inp.analysis_id, "calls": [e.call_id for e in envs], "committed": committed_keys}
    )
    result = {
        "analysis_id": inp.analysis_id,
        "bundle_id": bundle_id,
        "tools": [
            {"tool": e.tool, "call_id": e.call_id, "status": e.status, "output_hash": e.output_hash} for e in envs
        ],
        "committed": committed,
        "observed": observed,
        "allowed_numbers": numbers,
        "allowed_dates": sorted({d for s in displays for d in fmt.dates_in(s)}),
        "selection": "commit_keys" if inp.commit_keys is not None else "primary candidates",
    }
    return ToolOutput(result, [])
