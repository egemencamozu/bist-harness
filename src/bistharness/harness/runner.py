"""The stateful harness (CLAUDE.md §7): runs the 17 states in their fixed order for one AnalysisRequest.

Per state: not-applicable states are logged SKIPPED_NOT_APPLICABLE with the policy's reason (mandatory states never
are); analysis states execute the planner's proposals after a permission check (state -> tools) and an as_of lock
(a call for another as_of_date is rejected); rejected calls are logged as invalid_tool_call. CHECK_DATA_QUALITY,
BUILD_EVIDENCE and RISK_GATE are executed by the harness with arguments it builds from the run. After RUN_BACKTEST and
RISK_GATE the harness finalises the evidence bundle (internal build_evidence_bundle) so the committed set contains the
backtest and the gate result. A mandatory state without a valid proposal runs the scenario's default call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bistharness.core.enums import GateStatus, HarnessState, ReviewVerdict, StateStatus
from bistharness.core.errors import AsOfRequiredError, DataNotFoundError
from bistharness.core.hashing import sha256_hex
from bistharness.core.schemas import ToolEnvelope
from bistharness.harness.evidence import select_commit_keys
from bistharness.harness.explainer import Explainer, Explanation
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.planner import Planner, ScenarioPlanner, ToolCall
from bistharness.harness.policy import Policy, load_policy
from bistharness.harness.request import AnalysisRequest
from bistharness.tools import ToolContext, ToolInputError, run_tool

log = logging.getLogger(__name__)
S = HarnessState
ANALYSIS_STATES = frozenset(
    {
        S.LOAD_MARKET_DATA,
        S.CALCULATE_TECHNICALS,
        S.RUN_SECTOR_RELATIVE_ANALYSIS,
        S.RUN_PATTERN_AND_REVERSAL_ANALYSIS,
        S.LOAD_FUNDAMENTALS,
        S.LOAD_MACRO_CONTEXT,
        S.LOAD_NEWS_AND_SPEECH_CONTEXT,
        S.PREVIEW_STRATEGIES,
        S.RUN_BACKTEST,
    }
)


@dataclass
class CallRecord:
    state: HarnessState
    tool: str
    origin: str
    valid: bool
    arguments: dict[str, Any]
    error: str | None = None
    envelope: ToolEnvelope | None = None


@dataclass
class StateRecord:
    state: HarnessState
    status: StateStatus
    reason: str | None = None
    calls: list[CallRecord] = field(default_factory=list)


@dataclass
class Review:
    verdict: ReviewVerdict
    reason: str = ""
    modified_action: str | None = None
    reviewer: str = "human"


Reviewer = Callable[["AnalysisResult"], Review | None]


@dataclass
class HarnessConfig:
    planner: Planner
    explainer: Explainer
    memory: EpisodicMemory | None = None
    reviewer: Reviewer | None = None
    policy: Policy | None = None
    # UI hook: called with ("start" | "end", state, record) around every state. Display only: it receives the live
    # record, never changes the run, and an exception in it is logged and ignored.
    progress: Callable[[str, HarnessState, StateRecord], None] | None = None


@dataclass
class AnalysisResult:
    analysis_id: str
    request: AnalysisRequest
    policy_sha256: str
    states: list[StateRecord]
    bundle: dict[str, Any]
    gate: GateStatus
    gate_reasons: list[dict[str, str]]
    explanation: Explanation | None
    decision_id: str | None
    review: Review | None

    @property
    def calls(self) -> list[CallRecord]:
        return [c for s in self.states for c in s.calls]

    @property
    def invalid_calls(self) -> list[CallRecord]:
        return [c for c in self.calls if not c.valid]

    def envelope(self, tool: str) -> ToolEnvelope | None:
        envs = [c.envelope for c in self.calls if c.tool == tool and c.envelope is not None]
        return envs[-1] if envs else None


def new_analysis_id(req: AnalysisRequest) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"A-{stamp}-{sha256_hex(req.model_dump(mode='json'))[:8]}"


class _Run:
    def __init__(self, req: AnalysisRequest, ctx: ToolContext, cfg: HarnessConfig) -> None:
        self.req, self.ctx, self.cfg = req, ctx, cfg
        self.policy = cfg.policy or load_policy()
        self.defaults = ScenarioPlanner(self.policy)
        self.aid = new_analysis_id(req)
        self.seq = 0
        self.states: list[StateRecord] = []
        self.analysis_envs: list[ToolEnvelope] = []
        self.bundle: dict[str, Any] = {"committed": [], "observed": [], "allowed_numbers": [], "allowed_dates": []}
        self.gate = GateStatus.ANALYSIS_UNSAFE
        self.gate_reasons: list[dict[str, str]] = []
        self.hard_blocked = False
        self.mem = cfg.memory

    # ------------------------------------------------------------------ calls
    def execute(
        self, state: HarnessState, call: ToolCall, rec: StateRecord, *, internal: bool = False
    ) -> ToolEnvelope | None:
        self.seq += 1
        args = dict(call.arguments)
        error = None
        if not self.policy.allowed(state, call.tool, internal=internal):
            error = f"invalid_tool_call: {call.tool} is not permitted in {state.value}"
        elif str(args.get("as_of_date", "")) != self.req.as_of_date.isoformat():
            error = f"invalid_tool_call: as_of_date must be {self.req.as_of_date.isoformat()} (got {args.get('as_of_date')!r})"
        env = None
        if error is None:
            try:
                env = run_tool(call.tool, args, self.ctx)
            except (ToolInputError, AsOfRequiredError, DataNotFoundError, ValueError) as exc:
                error = f"invalid_tool_call: {type(exc).__name__}: {str(exc)[:300]}"
        cr = CallRecord(state, call.tool, call.origin, env is not None, args, error, env)
        rec.calls.append(cr)
        if self.mem:
            stored = env.model_dump(mode="json") if env else None
            if stored is not None and _carries_envelopes(args):
                # embedded envelopes are already stored in their own rows: keep only their call ids
                stored["inputs"] = _light(stored["inputs"])
                stored["inputs_lightened"] = True
            self.mem.log_tool_call(
                self.aid,
                self.seq,
                state=state.value,
                tool=call.tool,
                origin=call.origin,
                valid=env is not None,
                arguments=_light(args),
                error=error,
                envelope=stored,
            )
        if error:
            log.info("%s %s", self.aid, error)
        return env

    def build_bundle(
        self, state: HarnessState, rec: StateRecord, observed: list[ToolEnvelope], *, internal: bool
    ) -> None:
        keys = select_commit_keys(self.policy, self.req.scenario, self.req.tickers, observed)
        call = ToolCall(
            "build_evidence_bundle",
            {
                "as_of_date": self.req.as_of_date.isoformat(),
                "analysis_id": self.aid,
                "observed_context": [e.model_dump(mode="json") for e in observed],
                "commit_keys": keys,
                "max_committed": self.policy.max_committed,
            },
            origin="harness",
        )
        env = self.execute(state, call, rec, internal=internal)
        if env is not None:
            self.bundle = env.result
            if self.mem:
                self.mem.log_evidence(self.aid, self.bundle["committed"])

    def gate_call(
        self, state: HarnessState, rec: StateRecord, envelopes: list[ToolEnvelope], committed: list[str] | None
    ) -> ToolEnvelope | None:
        bundle = {
            "tickers": list(self.req.tickers),
            "start": self.req.start.isoformat(),
            "envelopes": [e.model_dump(mode="json") for e in envelopes],
            "committed_keys": committed,
        }
        if self.req.end is not None:
            bundle["end"] = self.req.end.isoformat()
        return self.execute(
            state,
            ToolCall(
                "check_data_quality",
                {"as_of_date": self.req.as_of_date.isoformat(), "analysis_bundle": bundle},
                origin="harness",
            ),
            rec,
        )

    # ------------------------------------------------------------------ states
    def run(self) -> AnalysisResult:
        req = self.req
        if self.mem:
            self.mem.start(
                self.aid,
                question=req.question,
                request=req.model_dump(mode="json"),
                scenario=req.scenario.value,
                as_of=req.as_of_date.isoformat(),
                planner=self.cfg.planner.name,
                explainer=self.cfg.explainer.name,
                policy_sha256=self.policy.sha256,
                data_version=self.ctx.data_version,
            )
        explanation: Explanation | None = None
        review: Review | None = None
        decision_id: str | None = None
        for state in self.policy.states:
            rec = StateRecord(state, StateStatus.DONE)
            self.notify("start", state, rec)
            reason = self.policy.skip_reason(req.scenario, state)
            if state in ANALYSIS_STATES and state not in self.policy.mandatory and (reason or self.hard_blocked):
                rec.status = StateStatus.SKIPPED_NOT_APPLICABLE
                rec.reason = reason or "CHECK_DATA_QUALITY sert blok verdi: analiz adımı çalıştırılmadı"
            elif state is S.SELECT_UNIVERSE:
                for t in req.tickers:
                    self.ctx.universe.instrument(t)
                rec.reason = f"tickers={list(req.tickers)}"
            elif state is S.CHECK_DATA_QUALITY:
                env = self.gate_call(state, rec, [], None)
                self.hard_blocked = env is not None and env.result.get("gate") == GateStatus.HARD_BLOCK.value
            elif state in ANALYSIS_STATES:
                done = [{"tool": c.tool, "arguments": c.arguments} for c in self.calls_so_far() if c.valid]
                proposals = self.cfg.planner.propose(state, req, done)
                self.log_planner()
                for call in proposals:
                    env = self.execute(state, call, rec)
                    if env is not None:
                        self.analysis_envs.append(env)
                if state in self.policy.mandatory and not any(c.valid for c in rec.calls):
                    for call in self.defaults.propose(state, req, done):
                        env = self.execute(state, ToolCall(call.tool, call.arguments, "harness_default"), rec)
                        if env is not None:
                            self.analysis_envs.append(env)
                if state is S.RUN_BACKTEST:
                    self.build_bundle(state, rec, self.analysis_envs, internal=True)
            elif state is S.BUILD_EVIDENCE:
                self.build_bundle(state, rec, self.analysis_envs, internal=False)
            elif state is S.RISK_GATE:
                keys = [c["key"] for c in self.bundle["committed"]]
                env = self.gate_call(state, rec, self.analysis_envs, keys)
                if env is not None:
                    self.gate = GateStatus(env.result["gate"])
                    self.gate_reasons = env.result["reasons"]
                    self.build_bundle(state, rec, [*self.analysis_envs, env], internal=True)
                else:
                    rec.status, rec.reason = StateStatus.FAILED, "risk gate could not run"
            elif state is S.GENERATE_EXPLANATION:
                explanation = self.cfg.explainer.explain(req, self.bundle, self.gate)
                self.log_llm(explanation)
                rec.reason = f"action={explanation.action.value} fallback={explanation.fallback_used}"
            elif state is S.HUMAN_REVIEW:
                decision_id = f"D-{self.aid[2:]}"
                if explanation is not None and self.mem:
                    last = explanation.attempts[-1] if explanation.attempts else None
                    self.mem.save_decision(
                        decision_id,
                        self.aid,
                        action=explanation.action.value,
                        text_tr=explanation.text_tr,
                        cited=explanation.cited,
                        gate=self.gate.value,
                        bundle_id=self.bundle.get("bundle_id"),
                        fallback_used=explanation.fallback_used,
                        teacher_action=explanation.teacher_action.value if explanation.teacher_action else None,
                        teacher_rule=explanation.teacher_rule,
                        model=last.model if last else None,
                        model_digest=last.digest if last else None,
                    )
                partial = self.result(explanation, decision_id, None)
                review = self.cfg.reviewer(partial) if self.cfg.reviewer else None
                if review is not None and review.verdict is not ReviewVerdict.PENDING and self.mem:
                    self.mem.add_review(
                        decision_id,
                        reviewer=review.reviewer,
                        verdict=review.verdict.value,
                        reason=review.reason,
                        modified_action=review.modified_action,
                    )
                rec.reason = review.verdict.value if review else ReviewVerdict.PENDING.value
            self.states.append(rec)
            if self.mem:
                self.mem.log_state(
                    self.aid, len(self.states), state.value, rec.status.value, rec.reason, len(rec.calls)
                )
            self.notify("end", state, rec)
        return self.result(explanation, decision_id, review)

    def notify(self, event: str, state: HarnessState, rec: StateRecord) -> None:
        if self.cfg.progress is None:
            return
        try:
            self.cfg.progress(event, state, rec)
        except Exception:  # a display hook must never break or alter an analysis
            log.exception("progress hook failed at %s %s", event, state.value)

    def calls_so_far(self) -> list[CallRecord]:
        return [c for s in self.states for c in s.calls]

    def log_planner(self) -> None:
        """Planner LLM calls (prompt, raw proposal, model digest) go to llm_calls with purpose plan:<state>."""
        drain = getattr(self.cfg.planner, "drain", None)
        if drain is None:
            return
        for pc in drain():
            if not self.mem:
                continue
            self.seq += 1
            r = pc.response
            self.mem.log_llm_call(
                self.aid,
                self.seq,
                purpose=f"plan:{pc.state}",
                model=r.model,
                digest=r.digest,
                prompt_hash=r.prompt_hash,
                messages=pc.messages,
                raw=r.text,
                validation={"proposed_calls": pc.n_proposed},
                seconds=r.seconds,
            )

    def log_llm(self, e: Explanation) -> None:
        if not self.mem:
            return
        for a in e.attempts:
            self.seq += 1
            self.mem.log_llm_call(
                self.aid,
                self.seq,
                purpose="explanation",
                model=a.model,
                digest=a.digest,
                prompt_hash=a.prompt_hash,
                messages=a.messages,
                raw=a.raw,
                validation={"ok": a.validation.ok, "errors": a.validation.errors, "checks": a.validation.checks},
                seconds=a.seconds,
            )

    def result(self, e: Explanation | None, decision_id: str | None, review: Review | None) -> AnalysisResult:
        return AnalysisResult(
            self.aid,
            self.req,
            self.policy.sha256,
            list(self.states),
            self.bundle,
            self.gate,
            self.gate_reasons,
            e,
            decision_id,
            review,
        )


def _carries_envelopes(args: dict[str, Any]) -> bool:
    return "observed_context" in args or bool((args.get("analysis_bundle") or {}).get("envelopes"))


def _light(args: dict[str, Any]) -> dict[str, Any]:
    """Arguments for the tool_calls table: embedded envelopes are replaced by their call ids (the envelopes themselves
    are stored in their own rows)."""
    out = dict(args)
    if "observed_context" in out:
        out["observed_context"] = [
            {"call_id": e.get("call_id"), "tool": e.get("tool")} for e in out["observed_context"]
        ]
    if "analysis_bundle" in out and isinstance(out["analysis_bundle"], dict):
        b = dict(out["analysis_bundle"])
        b["envelopes"] = [{"call_id": e.get("call_id"), "tool": e.get("tool")} for e in b.get("envelopes", [])]
        out["analysis_bundle"] = b
    return out


def run_analysis(req: AnalysisRequest, ctx: ToolContext, cfg: HarnessConfig) -> AnalysisResult:
    run = _Run(req, ctx, cfg)
    try:
        return run.run()
    except Exception as exc:
        if run.mem:
            run.mem.fail(run.aid, f"{type(exc).__name__}: {exc}")
        raise
