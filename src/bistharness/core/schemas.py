"""Pydantic models shared by tools, harness and memory. Every MCP tool returns a ToolEnvelope."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bistharness.core.enums import Severity, ToolStatus, WarningCode
from bistharness.core.hashing import sha256_hex


class WarningItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: WarningCode
    severity: Severity = Severity.SOFT
    detail: str = ""
    ticker: str | None = None
    date: dt.date | None = None


class ExcludedEvent(BaseModel):
    """An event left out of a forward-return statistic because its window is not complete at as_of."""

    model_config = ConfigDict(frozen=True)

    event_date: dt.date
    horizon: int
    trading_days_available: int
    reason: str = WarningCode.FORWARD_WINDOW_INCOMPLETE.value
    event_type: str | None = None
    ticker: str | None = None


class EvidenceCandidate(BaseModel):
    """A claim a tool offers to the evidence builder. `display` holds the exact strings the LLM may quote.

    key: deterministic id "<tool>.<subject>.<name>"; kind: "fact" (a measured value), "statistic" (a historical test
    result), "warning" (a limitation the explanation must mention); primary: the tool's headline claims, committed by
    default by build_evidence_bundle.
    """

    key: str
    claim_tr: str
    values: dict[str, Any] = Field(default_factory=dict)
    display: dict[str, str] = Field(default_factory=dict)
    json_pointer: str = ""
    kind: str = "fact"
    primary: bool = False


class ToolEnvelope(BaseModel):
    tool: str
    tool_version: str
    as_of_date: dt.date
    inputs: dict[str, Any]
    data_version: dict[str, str] = Field(default_factory=dict)
    status: ToolStatus = ToolStatus.OK
    result: dict[str, Any] = Field(default_factory=dict)
    warnings: list[WarningItem] = Field(default_factory=list)
    excluded_incomplete_events: list[ExcludedEvent] = Field(default_factory=list)
    evidence_candidates: list[EvidenceCandidate] = Field(default_factory=list)
    call_id: str = ""
    output_hash: str = ""
    generated_at: dt.datetime | None = None  # wall clock, excluded from both hashes

    def finalize(self) -> ToolEnvelope:
        """Fill call_id (hash of tool+version+as_of+inputs+data_version) and output_hash (hash of everything else)."""
        call_id = sha256_hex(
            {
                "tool": self.tool,
                "tool_version": self.tool_version,
                "as_of_date": self.as_of_date,
                "inputs": self.inputs,
                "data_version": self.data_version,
            }
        )
        body = self.model_dump(mode="json", exclude={"call_id", "output_hash", "generated_at"})
        return self.model_copy(update={"call_id": call_id, "output_hash": sha256_hex(body)})
