"""Scenario-aware selection of the committed evidence keys (patterns in config/harness_policy.yaml)."""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatchcase

from bistharness.core.enums import Scenario
from bistharness.core.schemas import ToolEnvelope
from bistharness.harness.policy import Policy


def produced_keys(envelopes: Sequence[ToolEnvelope]) -> list[tuple[str, str]]:
    """(key, kind) of every evidence candidate in envelope order (first occurrence wins)."""
    seen: dict[str, str] = {}
    for env in envelopes:
        for c in env.evidence_candidates:
            seen.setdefault(c.key, c.kind)
    return list(seen.items())


def select_commit_keys(
    policy: Policy, scenario: Scenario, tickers: Sequence[str], envelopes: Sequence[ToolEnvelope]
) -> list[str]:
    """Pattern order defines E# order; {t} expands to every analysed ticker (ticker order within a pattern)."""
    keys = produced_keys(envelopes)
    patterns: list[str] = []
    for p in [*policy.evidence_patterns.get(scenario, ()), *policy.evidence_always]:
        patterns += [p.replace("{t}", t) for t in tickers] if "{t}" in p else [p]
    chosen: list[str] = []
    for pat in patterns:
        for k, _ in keys:
            if k not in chosen and fnmatchcase(k, pat):
                chosen.append(k)
    if len(chosen) > policy.max_committed:
        # protected: the gate result, every backtest result (needed by *_CANDIDATE actions) and every warning
        kinds = dict(keys)
        always = [p for p in policy.evidence_always]
        protected = {
            k
            for k in chosen
            if kinds[k] == "warning" or k.startswith("backtest.") or any(fnmatchcase(k, a) for a in always)
        }
        room = max(0, policy.max_committed - len(protected))
        rest = [k for k in chosen if k not in protected][:room]
        keep = protected | set(rest)
        chosen = [k for k in chosen if k in keep]
    return chosen
