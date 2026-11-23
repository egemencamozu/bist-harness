"""check_data_quality — the risk & data-quality gate (CLAUDE.md §4).

Runs twice in the harness: CHECK_DATA_QUALITY (prices of the analysed tickers) and RISK_GATE (the final bundle:
every tool envelope + the committed evidence keys). Deterministic rules, worst level wins:

HARD_BLOCK      a hard-severity flag or warning (BROKEN_PRICE_SERIES, NON_POSITIVE_PRICE, LOOK_AHEAD, ...); any date in a
                tool result later than as_of; an envelope computed for another as_of (PERIOD_MISMATCH); an envelope
                whose output hash does not match its content (ENVELOPE_HASH_MISMATCH)
ANALYSIS_UNSAFE a requested ticker without prices; a malformed envelope; a tool ERROR; a committed evidence key that no
                tool produced
INVESTIGATE     a tool returned INSUFFICIENT_DATA; a committed statistic with n < insufficient_sample (5)
PASS_WITH_WARNINGS any soft warning (SMALL_SAMPLE on committed evidence, TMS29_WARNING, SMALL_SECTOR_GROUP, STALE_PRICE,
                MISSING_MACRO, SPARSE_NEWS, LOW_TRANSCRIPT_QUALITY, SUSPICIOUS_JUMP ...)
PASS            nothing of the above
Sample-size warnings that tools attach to every tested event type are NOT escalated: only the committed evidence
decides (an untested side statistic with n=2 must not block an analysis that does not use it).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from bistharness.core import formatting as fmt
from bistharness.core.enums import ALLOWED_ACTIONS_BY_GATE, HARD_BLOCK_CODES, GateStatus, Severity, WarningCode
from bistharness.core.errors import DataNotFoundError
from bistharness.core.schemas import ToolEnvelope
from bistharness.tools import common
from bistharness.tools.base import ToolContext, ToolInput, ToolOutput, strip_wall_clock, tool

ORDER = [
    GateStatus.PASS,
    GateStatus.PASS_WITH_WARNINGS,
    GateStatus.INVESTIGATE,
    GateStatus.ANALYSIS_UNSAFE,
    GateStatus.HARD_BLOCK,
]
NOT_ESCALATED = {WarningCode.SMALL_SAMPLE, WarningCode.INSUFFICIENT_SAMPLE, WarningCode.MULTIPLE_TESTING_RISK}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


class AnalysisBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tickers: list[str] = Field(default_factory=list)
    start: date | None = None
    end: date | None = None
    envelopes: list[dict[str, Any]] = Field(default_factory=list)
    committed_keys: list[str] | None = None

    @field_validator("envelopes")
    @classmethod
    def _no_wall_clock(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return strip_wall_clock(v)


class QualityInput(ToolInput):
    analysis_bundle: AnalysisBundle = Field(default_factory=AnalysisBundle)


def _future_dates(obj: Any, bound: str, path: str = "") -> list[str]:
    """JSON paths of ISO date/datetime strings after `bound` ('YYYY-MM-DD 23:59:59')."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _future_dates(v, bound, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _future_dates(v, bound, f"{path}/{i}")
    elif isinstance(obj, str) and _ISO.match(obj):
        s = obj.replace("T", " ")
        if (s if len(s) > 10 else s + " 00:00:00") > bound:
            out.append(f"{path}={obj}")
    return out


class _Gate:
    def __init__(self) -> None:
        self.level = GateStatus.PASS
        self.reasons: list[dict[str, str]] = []

    def add(self, level: GateStatus, code: str, detail: str) -> None:
        if ORDER.index(level) > ORDER.index(self.level):
            self.level = level
        self.reasons.append({"level": level.value, "code": code, "detail": detail})


@tool(
    "check_data_quality",
    version="1.0.0",
    input_model=QualityInput,
    sources=("prices",),
    description="Risk & data-quality gate over an analysis bundle (tickers, window, tool envelopes, committed "
    "evidence keys): hard blocks (look-ahead, broken series, period mismatch, tampered output) and soft warnings "
    "-> PASS / PASS_WITH_WARNINGS / INVESTIGATE / ANALYSIS_UNSAFE / HARD_BLOCK and the allowed actions.",
)
def check_data_quality(ctx: ToolContext, inp: QualityInput) -> ToolOutput:
    b = inp.analysis_bundle
    as_of = inp.as_of_date
    bound = f"{as_of.isoformat()} 23:59:59"
    gate = _Gate()
    w = common.window(ctx, b.start, b.end, as_of)
    cal = common.calendar(ctx, as_of)
    stale_days = int(ctx.settings.threshold("stale_run_days"))
    # 1) prices of the analysed tickers
    for t in b.tickers:
        inst = common.instrument(ctx, t)
        try:
            px = ctx.repo.prices(inst.ticker, w.start, w.end, as_of=as_of).data
        except DataNotFoundError:
            px = pd.DataFrame()
        if px.empty:
            gate.add(GateStatus.ANALYSIS_UNSAFE, "NO_PRICE_DATA", f"{inst.ticker}: no price in {w.start}..{w.end}")
            continue
        last = px["date"].max().date()
        gap = cal.days_after(last) if cal.last and last < w.end else 0
        if gap > stale_days:
            gate.add(
                GateStatus.PASS_WITH_WARNINGS,
                WarningCode.STALE_PRICE.value,
                f"{inst.ticker}: last price {last}, {gap} trading days before the window end",
            )
        flags = ctx.repo.quality_flags(inst.ticker, w.start, w.end, as_of=as_of)
        for (code, sev), grp in flags.groupby(["code", "severity"], sort=True):
            wc = WarningCode(code)
            if sev == Severity.HARD or wc in HARD_BLOCK_CODES:
                gate.add(GateStatus.HARD_BLOCK, code, f"{inst.ticker}: {len(grp)} x {code} in the window")
            elif sev == Severity.SOFT:
                gate.add(GateStatus.PASS_WITH_WARNINGS, code, f"{inst.ticker}: {len(grp)} x {code} in the window")
    # 2) tool envelopes
    produced: dict[str, dict[str, Any]] = {}
    for i, raw in enumerate(b.envelopes):
        try:
            env = ToolEnvelope.model_validate(raw)
        except ValidationError as exc:
            gate.add(GateStatus.ANALYSIS_UNSAFE, "MALFORMED_ENVELOPE", f"envelope {i}: {exc.error_count()} error(s)")
            continue
        name = f"{env.tool}#{i}"
        if env.finalize().output_hash != env.output_hash or env.finalize().call_id != env.call_id:
            gate.add(
                GateStatus.HARD_BLOCK,
                WarningCode.ENVELOPE_HASH_MISMATCH.value,
                f"{name}: content does not match its hash",
            )
        if env.as_of_date != as_of:
            gate.add(
                GateStatus.HARD_BLOCK,
                WarningCode.PERIOD_MISMATCH.value,
                f"{name}: computed for as_of {env.as_of_date}, analysis as_of {as_of}",
            )
        future = _future_dates(env.model_dump(mode="json", include={"result", "excluded_incomplete_events"}), bound)
        if future:
            gate.add(GateStatus.HARD_BLOCK, WarningCode.LOOK_AHEAD.value, f"{name}: dates after as_of {future[:3]}")
        if env.status.value == "ERROR":
            gate.add(GateStatus.ANALYSIS_UNSAFE, "TOOL_ERROR", f"{name} failed")
        elif env.status.value == "INSUFFICIENT_DATA":
            gate.add(GateStatus.INVESTIGATE, "INSUFFICIENT_DATA", f"{name}: insufficient data")
        for wi in env.warnings:
            if wi.severity == Severity.HARD or wi.code in HARD_BLOCK_CODES:
                gate.add(GateStatus.HARD_BLOCK, wi.code.value, f"{name}: {wi.detail}")
            elif wi.severity == Severity.SOFT and wi.code not in NOT_ESCALATED:
                gate.add(GateStatus.PASS_WITH_WARNINGS, wi.code.value, f"{name}: {wi.detail}")
        for c in env.evidence_candidates:
            produced[c.key] = {"kind": c.kind, "values": c.values}
    # 3) committed evidence
    small, insufficient = (
        int(ctx.settings.threshold("small_sample")),
        int(ctx.settings.threshold("insufficient_sample")),
    )
    for key in b.committed_keys or []:
        if key not in produced:
            gate.add(
                GateStatus.ANALYSIS_UNSAFE, "UNSUPPORTED_EVIDENCE", f"committed key {key!r} is not in any tool output"
            )
            continue
        n = produced[key]["values"].get("n")
        if produced[key]["kind"] == "statistic" and isinstance(n, int | float):
            if n < insufficient:
                gate.add(
                    GateStatus.INVESTIGATE, WarningCode.INSUFFICIENT_SAMPLE.value, f"{key}: n={int(n)} < {insufficient}"
                )
            elif n < small:
                gate.add(GateStatus.PASS_WITH_WARNINGS, WarningCode.SMALL_SAMPLE.value, f"{key}: n={int(n)} < {small}")
    allowed = sorted(a.value for a in ALLOWED_ACTIONS_BY_GATE[gate.level])
    reasons = sorted(gate.reasons, key=lambda r: (-ORDER.index(GateStatus(r["level"])), r["code"], r["detail"]))
    result = {
        "gate": gate.level,
        "allowed_actions": allowed,
        "reasons": reasons,
        "checked": {"tickers": b.tickers, "envelopes": len(b.envelopes), "committed_keys": len(b.committed_keys or [])},
    }
    disp = {"gate": gate.level.value, "n": fmt.integer(len(reasons))}
    ev = [
        common.evidence(
            "gate.result",
            "Risk ve veri kalitesi kapısı sonucu {gate} ({n} bulgu).",
            disp,
            values={"gate": gate.level.value, "allowed_actions": allowed},
            pointer="/result/gate",
            kind="warning" if gate.level != GateStatus.PASS else "fact",
            primary=True,
        )
    ]
    return ToolOutput(result, [], evidence=ev)
