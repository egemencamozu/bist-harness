"""Tool infrastructure: validated inputs -> point-in-time reads -> analytics -> deterministic ToolEnvelope.

A tool is a thin layer (CLAUDE.md §5): it validates its pydantic input (as_of_date is mandatory), reads ONLY
through PITRepository, calls pure analytics functions and returns a ToolOutput. `run_tool` wraps it in a
ToolEnvelope: inputs as validated, the data_version of the sources it read, floats rounded to
settings.determinism.float_decimals, call_id = sha256(tool, version, as_of, inputs, data_version) and an
output_hash over everything except the wall-clock `generated_at`. The same call on the same snapshot therefore
always returns byte-identical envelopes.
"""

from __future__ import annotations

import dataclasses
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from functools import cached_property
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError

from bistharness.core.config import Settings, Universe, load_settings, load_universe
from bistharness.core.enums import Severity, ToolStatus
from bistharness.core.errors import AsOfRequiredError
from bistharness.core.pit import PITRepository
from bistharness.core.schemas import EvidenceCandidate, ExcludedEvent, ToolEnvelope, WarningItem

log = logging.getLogger(__name__)


class ToolInput(BaseModel):
    """Base of every tool input: unknown fields are rejected, as_of_date is required."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of_date: date


class ToolInputError(ValueError):
    """Invalid tool call (unknown tool, missing as_of_date, bad field): logged as invalid_tool_call by the harness."""


@dataclass
class ToolContext:
    repo: PITRepository
    settings: Settings
    universe: Universe

    @classmethod
    def from_settings(cls) -> ToolContext:
        s = load_settings()
        return cls(PITRepository(s.db_path), s, load_universe())

    @cached_property
    def data_version(self) -> dict[str, str]:
        return self.repo.data_version()


@dataclass
class ToolOutput:
    result: dict[str, Any]
    warnings: list[WarningItem] = field(default_factory=list)
    excluded: list[ExcludedEvent] = field(default_factory=list)
    evidence: list[EvidenceCandidate] = field(default_factory=list)
    status: ToolStatus | None = None  # None -> OK / OK_WITH_WARNINGS from the warnings


@dataclass(frozen=True)
class ToolDef:
    name: str
    version: str
    description: str
    input_model: type[ToolInput]
    handler: Callable[[ToolContext, Any], ToolOutput]
    sources: tuple[str, ...]  # data_version keys the tool reads


REGISTRY: dict[str, ToolDef] = {}


def tool(
    name: str, *, version: str, input_model: type[ToolInput], sources: tuple[str, ...], description: str
) -> Callable[[Callable[[ToolContext, Any], ToolOutput]], Callable[[ToolContext, Any], ToolOutput]]:
    def deco(fn: Callable[[ToolContext, Any], ToolOutput]) -> Callable[[ToolContext, Any], ToolOutput]:
        if name in REGISTRY:
            raise ValueError(f"duplicate tool {name}")
        REGISTRY[name] = ToolDef(name, version, description, input_model, fn, sources)
        return fn

    return deco


# ----------------------------------------------------------------------------------------------- serialisation
def jsonable(obj: Any, decimals: int = 6) -> Any:
    """Plain JSON types; floats rounded (NaN/inf -> None); dates ISO; dataclasses/pydantic/pandas unpacked."""
    if obj is None or isinstance(obj, bool | str):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, int | np.integer):
        return int(obj)
    if isinstance(obj, float | np.floating):
        v = float(obj)
        return None if not math.isfinite(v) else round(v, decimals) + 0.0  # +0.0 turns -0.0 into 0.0
    if isinstance(obj, pd.Timestamp):
        return obj.date().isoformat() if obj == obj.normalize() else obj.isoformat()
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, BaseModel):
        return jsonable(obj.model_dump(mode="python"), decimals)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name), decimals) for f in dataclasses.fields(obj)}
    if isinstance(obj, pd.DataFrame):
        return [jsonable(r, decimals) for r in obj.to_dict("records")]
    if isinstance(obj, pd.Series):
        return {str(jsonable(k, decimals)): jsonable(v, decimals) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {str(jsonable(k, decimals)): jsonable(v, decimals) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set | frozenset | np.ndarray):
        items = sorted(obj) if isinstance(obj, set | frozenset) else list(obj)
        return [jsonable(v, decimals) for v in items]
    if obj is pd.NaT:
        return None
    raise TypeError(f"not serialisable: {type(obj).__name__}")


def strip_wall_clock(envelopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Embedded envelopes are inputs of other tools: their wall-clock `generated_at` must not enter call_id."""
    return [{k: v for k, v in e.items() if k != "generated_at"} if isinstance(e, dict) else e for e in envelopes]


def run_tool(name: str, inputs: dict[str, Any], ctx: ToolContext) -> ToolEnvelope:
    if name not in REGISTRY:
        raise ToolInputError(f"unknown tool {name!r}")
    td = REGISTRY[name]
    if not inputs.get("as_of_date"):
        raise AsOfRequiredError(f"{name}: as_of_date is mandatory")
    try:
        inp = td.input_model.model_validate(inputs)
    except ValidationError as exc:
        raise ToolInputError(f"{name}: invalid input: {exc.errors(include_url=False)}") from exc
    out = td.handler(ctx, inp)
    decimals = ctx.settings.float_decimals
    status = out.status
    if status is None:
        status = (
            ToolStatus.OK_WITH_WARNINGS if any(w.severity != Severity.INFO for w in out.warnings) else ToolStatus.OK
        )
    env = ToolEnvelope(
        tool=td.name,
        tool_version=td.version,
        as_of_date=inp.as_of_date,
        inputs=jsonable(inp.model_dump(mode="python"), decimals),
        data_version={k: v for k, v in ctx.data_version.items() if k in td.sources},
        status=status,
        result=jsonable(out.result, decimals),
        warnings=_dedupe(out.warnings),
        excluded_incomplete_events=sorted(
            out.excluded, key=lambda e: (e.ticker or "", e.event_type or "", e.event_date, e.horizon)
        ),
        evidence_candidates=[
            c.model_copy(update={"values": jsonable(c.values, decimals)})
            for c in sorted(out.evidence, key=lambda c: c.key)
        ],
        generated_at=datetime.now(UTC).replace(microsecond=0),
    )
    return env.finalize()


def _dedupe(warnings: list[WarningItem]) -> list[WarningItem]:
    seen: set[tuple[Any, ...]] = set()
    out: list[WarningItem] = []
    for w in warnings:
        k = (w.code, w.severity, w.detail, w.ticker, w.date)
        if k not in seen:
            seen.add(k)
            out.append(w)
    return sorted(out, key=lambda w: (w.code.value, w.ticker or "", w.detail))


def envelope_digest(env: ToolEnvelope) -> str:
    """The hash that must not change between identical calls (excludes generated_at)."""
    return env.output_hash


def warn(code: Any, detail: str, *, severity: Severity = Severity.SOFT, ticker: str | None = None) -> WarningItem:
    return WarningItem(code=code, severity=severity, detail=detail, ticker=ticker)
