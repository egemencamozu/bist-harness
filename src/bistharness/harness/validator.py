"""Programmatic output audit (CLAUDE.md §4): an explanation is accepted only if

(a) it parses into the JSON schema (LLMOutput);
(b) the action is one of the 8 and allowed by the gate; a *_CANDIDATE action cites a backtest evidence;
(c) every number it writes is a number of the committed evidence display strings (E# labels, the fixed templates
    and the analysis date are not "numbers"); every date it writes is a committed date or the as_of date;
(d) no forbidden phrase (advice, target price, certainty, guarantee, buy/sell) appears in the model's own text;
(e) every cited / mentioned E# exists, at least one is cited, and an advice request sets refusal_needed.
The harness prepends the fixed refusal template itself, so the model never has to write forbidden words.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bistharness.core import formatting as fmt
from bistharness.core.enums import ALLOWED_ACTIONS_BY_GATE, CANDIDATE_ACTIONS, AnalyticalAction, GateStatus
from bistharness.harness.policy import ValidationRules

EID_RE = re.compile(r"\bE(\d{1,3})\b")


class LLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: AnalyticalAction
    explanation_tr: str = Field(min_length=20)
    cited_evidence: list[str] = Field(default_factory=list)
    refusal_needed: bool = False
    limitations_tr: str = ""


def output_schema(allowed: list[str]) -> dict[str, Any]:
    """JSON schema given to Ollama `format` (the action enum is the gate's allowed set)."""
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": allowed},
            # length caps bound greedy repetition loops (a looping answer ran into num_ctx and came back as truncated
            # JSON). Longest training target 1.890 / 467 chars. Ollama 0.40 enforces 2.000 but silently ignored 2.400
            # (measured 2026-11-23: a 9.342-char loop), so keep caps <= 2.000.
            "explanation_tr": {"type": "string", "maxLength": 2000},
            "cited_evidence": {  # at most max_committed (16) evidence items exist; bounds decoding loops
                "type": "array",
                "items": {"type": "string", "pattern": "^E[0-9]+$"},
                "maxItems": 16,
            },
            "refusal_needed": {"type": "boolean"},
            "limitations_tr": {"type": "string", "maxLength": 800},
        },
        "required": ["action", "explanation_tr", "cited_evidence", "refusal_needed", "limitations_tr"],
    }


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    output: LLMOutput | None = None
    bad_numbers: list[float] = field(default_factory=list)
    forbidden_hits: list[str] = field(default_factory=list)


def _strip(text: str, rules: ValidationRules) -> str:
    out = text
    for t in (rules.refusal_template, rules.disclaimer, *rules.allowed_phrases):
        out = re.sub(re.escape(t), " ", out, flags=re.IGNORECASE)
    return out


def validate(
    raw: str | dict[str, Any],
    *,
    committed: list[dict[str, Any]],
    allowed_numbers: list[float],
    allowed_dates: list[str],
    gate: GateStatus,
    rules: ValidationRules,
    as_of: date,
    advice_requested: bool,
) -> ValidationResult:
    res = ValidationResult(ok=False)
    # (a) schema
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        out = LLMOutput.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        res.errors.append(f"schema: {str(exc).splitlines()[0][:200]}")
        res.checks["schema"] = False
        return res
    res.output = out
    res.checks["schema"] = True
    ids = {c["id"]: c for c in committed}
    text = f"{out.explanation_tr}\n{out.limitations_tr}"
    # (b) action / gate mapping
    allowed = ALLOWED_ACTIONS_BY_GATE[gate]
    res.checks["action_allowed"] = out.action in allowed
    if not res.checks["action_allowed"]:
        res.errors.append(
            f"action {out.action.value} is not allowed under gate {gate.value}; allowed: "
            f"{sorted(a.value for a in allowed)}"
        )
    cited = list(dict.fromkeys(out.cited_evidence + [f"E{m}" for m in EID_RE.findall(text)]))
    if rules.candidate_needs_backtest and out.action in CANDIDATE_ACTIONS:
        has_bt = any(ids.get(c, {}).get("key", "").startswith("backtest.") for c in cited)
        res.checks["candidate_backtest"] = has_bt
        if not has_bt:
            res.errors.append(f"{out.action.value} requires citing a backtest evidence (backtest.*)")
    # (e) citations
    missing = [c for c in cited if c not in ids]
    res.checks["citations_exist"] = not missing
    if missing:
        res.errors.append(f"cited evidence does not exist: {missing}")
    res.checks["has_citation"] = bool(cited) or not rules.require_citation
    if not res.checks["has_citation"]:
        res.errors.append("no evidence (E#) is cited")
    if advice_requested:
        res.checks["refusal"] = out.refusal_needed
        if not out.refusal_needed:
            res.errors.append("the question asks for advice/target price: refusal_needed must be true")
    # (c) numbers (value AND kind: percent vs plain) and dates; a bare year is fine when it is the year of a
    # committed date / fiscal period or of as_of
    clean = _strip(EID_RE.sub(" ", text), rules)
    as_of_forms = {fmt.tr_date(as_of), as_of.isoformat()}
    dates = fmt.dates_in(clean)
    bad_dates = [d for d in dates if d not in set(allowed_dates) | as_of_forms]
    shown = [v for c in committed for v in c.get("display", {}).values()] + [c.get("claim_tr", "") for c in committed]
    typed = {t for s in shown for t in fmt.typed_numbers_in(s)} if shown else set()
    allowed_set = set(allowed_numbers)
    years = {as_of.year} | {y for s in [*shown, *allowed_dates] for y in fmt.years_in(s)}

    def ok(kind: str, n: float) -> bool:
        if kind == "num" and n.is_integer() and int(n) in years:
            return True
        return (kind, n) in typed if typed else n in allowed_set

    bad = [n for kind, n in fmt.typed_numbers_in(clean) if not ok(kind, n)]
    res.bad_numbers = bad
    res.checks["numbers"] = not bad
    res.checks["dates"] = not bad_dates
    if bad:
        res.errors.append(f"numbers not found in the committed evidence: {sorted(set(bad))[:10]}")
    if bad_dates:
        res.errors.append(f"dates not found in the committed evidence: {bad_dates[:5]}")
    # (d) forbidden phrases on the model's own text
    hits = [m.group(0) for rx in rules.forbidden for m in rx.finditer(_strip(text, rules))]
    res.forbidden_hits = hits
    res.checks["forbidden"] = not hits
    if hits:
        res.errors.append(f"forbidden phrases: {hits[:5]}")
    res.ok = not res.errors
    return res
