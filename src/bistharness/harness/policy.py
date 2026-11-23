"""Typed view of config/harness_policy.yaml (procedural memory), validated on load."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any

from bistharness.core.config import read_config_yaml
from bistharness.core.enums import HarnessState, Scenario
from bistharness.core.errors import ConfigError
from bistharness.core.hashing import sha256_hex
from bistharness.tools import TOOL_NAMES


@dataclass(frozen=True)
class ValidationRules:
    max_attempts: int
    require_citation: bool
    candidate_needs_backtest: bool
    forbidden: tuple[re.Pattern[str], ...]
    allowed_phrases: tuple[str, ...]
    refusal_template: str
    disclaimer: str
    unsafe_template: str


@dataclass(frozen=True)
class Policy:
    raw: dict[str, Any]
    sha256: str
    states: tuple[HarnessState, ...]
    mandatory: frozenset[HarnessState]
    permissions: dict[HarnessState, frozenset[str]]
    harness_internal: frozenset[str]
    not_applicable: dict[Scenario, dict[HarnessState, str]]
    backtest_variant: dict[Scenario, str]
    split_date: date
    evidence_always: tuple[str, ...]
    evidence_patterns: dict[Scenario, tuple[str, ...]]
    max_committed: int
    validation: ValidationRules
    decision: dict[str, float]
    llm: dict[str, Any]

    def allowed(self, state: HarnessState, tool: str, *, internal: bool = False) -> bool:
        return tool in self.permissions[state] or (internal and tool in self.harness_internal)

    def skip_reason(self, scenario: Scenario, state: HarnessState) -> str | None:
        return self.not_applicable.get(scenario, {}).get(state)


def policy_from_dict(raw: dict[str, Any]) -> Policy:
    states = tuple(HarnessState(s) for s in raw["states"])
    if states != tuple(HarnessState):
        raise ConfigError("harness_policy.states must list every HarnessState in the fixed order")
    mandatory = frozenset(HarnessState(s) for s in raw["mandatory"])
    if mandatory != {HarnessState.CHECK_DATA_QUALITY, HarnessState.RUN_BACKTEST, HarnessState.RISK_GATE}:
        raise ConfigError("mandatory states are CHECK_DATA_QUALITY, RUN_BACKTEST and RISK_GATE (CLAUDE.md §1.6)")
    perms = {HarnessState(k): frozenset(v or []) for k, v in raw["permissions"].items()}
    if set(perms) != set(HarnessState):
        raise ConfigError("permissions must cover every state")
    unknown = {t for v in perms.values() for t in v} - set(TOOL_NAMES)
    if unknown:
        raise ConfigError(f"permissions reference unknown tools {sorted(unknown)}")
    na = {Scenario(s): {HarnessState(k): str(r) for k, r in m.items()} for s, m in raw["not_applicable"].items()}
    for s, m in na.items():
        bad = set(m) & mandatory
        if bad:
            raise ConfigError(f"{s}: mandatory states cannot be skipped: {sorted(bad)}")
    v = raw["validation"]
    rules = ValidationRules(
        max_attempts=int(v["max_attempts"]),
        require_citation=bool(v["require_citation"]),
        candidate_needs_backtest=bool(v["candidate_needs_backtest"]),
        forbidden=tuple(re.compile(p, re.IGNORECASE) for p in v["forbidden_patterns"]),
        allowed_phrases=tuple(v.get("allowed_phrases", [])),
        refusal_template=" ".join(str(v["refusal_template"]).split()),
        disclaimer=" ".join(str(v["disclaimer"]).split()),
        unsafe_template=" ".join(str(v["unsafe_template"]).split()),
    )
    ev = raw["evidence"]
    return Policy(
        raw=raw,
        sha256=sha256_hex(raw),
        states=states,
        mandatory=mandatory,
        permissions=perms,
        harness_internal=frozenset(raw.get("harness_internal", [])),
        not_applicable=na,
        backtest_variant={Scenario(k): str(x) for k, x in raw["backtest_variant"].items()},
        split_date=date.fromisoformat(str(raw["backtest_split_date"])),
        evidence_always=tuple(ev.get("always", [])),
        evidence_patterns={Scenario(k): tuple(x) for k, x in ev.items() if k in Scenario.__members__},
        max_committed=int(ev["max_committed"]),
        validation=rules,
        decision={k: float(x) for k, x in raw["decision"].items()},
        llm=dict(raw["llm"]),
    )


@lru_cache(maxsize=2)
def load_policy() -> Policy:
    return policy_from_dict(read_config_yaml("harness_policy.yaml"))
