"""Planners propose tool calls for the analysis states; the harness validates and executes them.

- ScenarioPlanner: deterministic default calls per scenario and state (golden runs, dataset generation, fallback).
- LLMPlanner: the local LLM proposes calls for a state, constrained to that state's permitted tools by a JSON schema;
  every proposal is still checked by the harness (permission + tool input model) and invalid ones are logged.
CHECK_DATA_QUALITY, BUILD_EVIDENCE and RISK_GATE arguments are built by the harness itself (they carry the run's
envelopes), never by a planner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from bistharness.core.enums import HarnessState, Scenario
from bistharness.harness.llm_client import LLMClient, LLMResponse
from bistharness.harness.policy import Policy
from bistharness.harness.request import AnalysisRequest
from bistharness.tools import REGISTRY
from bistharness.tools.weekday_tool import WEEKDAY_PRESETS

S = HarnessState
HARNESS_BUILT = frozenset({S.CHECK_DATA_QUALITY, S.BUILD_EVIDENCE, S.RISK_GATE})


@dataclass(frozen=True)
class ToolCall:
    tool: str
    arguments: dict[str, Any]
    origin: str = "plan"  # plan | llm | harness_default | harness


class Planner(Protocol):
    name: str

    def propose(self, state: HarnessState, req: AnalysisRequest, done: list[dict[str, Any]]) -> list[ToolCall]: ...


def _base(req: AnalysisRequest) -> dict[str, Any]:
    return {"as_of_date": req.as_of_date.isoformat()}


def _window(req: AnalysisRequest) -> dict[str, Any]:
    out = {**_base(req), "start": req.start.isoformat()}
    if req.end is not None:
        out["end"] = req.end.isoformat()
    return out


def _recent(req: AnalysisRequest, days: int = 30) -> dict[str, Any]:
    end = req.end or req.as_of_date
    return {**_base(req), "start": (end - timedelta(days=days)).isoformat(), "end": end.isoformat()}


@dataclass
class ScenarioPlanner:
    policy: Policy
    name: str = "scenario_plan_v1"

    def propose(self, state: HarnessState, req: AnalysisRequest, done: list[dict[str, Any]]) -> list[ToolCall]:
        calls = [ToolCall(t, a) for t, a in self._calls(state, req)]
        return calls

    def _backtest(self, req: AnalysisRequest, variant: str, *, final: bool) -> dict[str, Any]:
        args: dict[str, Any] = {**_window(req), "universe": list(req.tickers), "variant": variant}
        end = req.end or req.as_of_date
        if req.start < self.policy.split_date <= end:  # an out-of-sample split only when it lies inside the window
            args["split_date"] = self.policy.split_date.isoformat()
        pattern = str(req.params.get("pattern", "MON_TUE_WED_DOWN__THU_FRI"))
        if req.scenario is Scenario.S2_WEEKDAY_PATTERN and pattern in WEEKDAY_PRESETS:
            # weekday patterns are backtested as executable rules; sequence patterns use the default preset
            pat = WEEKDAY_PRESETS[pattern]
            args["strategy_spec"] = {
                "weekday_condition": [list(c) for c in pat.condition],
                "holding_days": len(pat.outcome),
            }
        if req.scenario is Scenario.S2_WEEKDAY_PATTERN:
            args["split_date"] = str(req.params.get("out_of_sample_start", "2026-01-01"))
        if final:
            args["include_equity"] = True
            args["max_trades_listed"] = 50
        else:
            args["max_trades_listed"] = 0
        return args

    def _calls(self, state: HarnessState, req: AnalysisRequest) -> list[tuple[str, dict[str, Any]]]:
        sc, tk = req.scenario, list(req.tickers)
        variant = self.policy.backtest_variant[sc]
        if state is S.LOAD_MARKET_DATA:
            return [("get_stock_history", {**_window(req), "ticker": t}) for t in tk] + [
                ("get_index_history", _window(req))
            ]
        if state is S.CALCULATE_TECHNICALS:
            out = [("calculate_indicators", {**_base(req), "ticker": t}) for t in tk]
            if sc is Scenario.S3_TECHNICAL_REVERSAL:
                out.append(("find_support_resistance", {**_window(req), "ticker": tk[0]}))
            return out
        if state is S.RUN_SECTOR_RELATIVE_ANALYSIS:
            group = tk if len(tk) > 1 else tk[0]
            return [
                (
                    "rank_sector_relative_strength",
                    {**_window(req), "sector_or_tickers": group, "horizon": int(req.params.get("horizon", 20))},
                )
            ]
        if state is S.RUN_PATTERN_AND_REVERSAL_ANALYSIS:
            if sc is Scenario.S2_WEEKDAY_PATTERN:
                p = req.params
                return [
                    (
                        "test_weekday_pattern",
                        {
                            **_base(req),
                            "ticker": tk[0],
                            "pattern": p.get("pattern", "MON_TUE_WED_DOWN__THU_FRI"),
                            "in_sample_start": str(p.get("in_sample_start", req.start.isoformat())),
                            "in_sample_end": str(p.get("in_sample_end", "2025-12-31")),
                            "out_of_sample_start": str(p.get("out_of_sample_start", "2026-01-01")),
                            "tx_cost_bps": float(p.get("tx_cost_bps", 10.0)),
                        },
                    )
                ]
            return [("detect_reversal_events", {**_window(req), "ticker": tk[0]})]
        if state is S.LOAD_FUNDAMENTALS:
            out = []
            if sc is Scenario.S4_FUNDAMENTAL_REACTION:
                out.append(("get_fundamental_metrics", {**_window(req), "ticker": tk[0]}))
            out += [("calculate_fundamental_change", {**_window(req), "ticker": t}) for t in tk]
            return out
        if state is S.LOAD_MACRO_CONTEXT:
            args = _window(req)
            if sc is Scenario.SAFETY_ADVICE_REQUEST:
                args["ticker_for_corr"] = tk[0]
            return [("get_macro_context", args)]
        if state is S.LOAD_NEWS_AND_SPEECH_CONTEXT:
            news = [("get_news_events", {**_recent(req), "ticker_or_topic": t}) for t in tk]
            if sc is Scenario.SAFETY_ADVICE_REQUEST:
                return news
            return news + [("get_speech_features", {**_base(req), "source_id_or_topic": t}) for t in tk]
        if state is S.PREVIEW_STRATEGIES:
            return [("run_backtest", self._backtest(req, "ALL", final=False))]
        if state is S.RUN_BACKTEST:
            return [("run_backtest", self._backtest(req, variant, final=True))]
        return []


# ----------------------------------------------------------------------------------------------- LLM planner
PLANNER_SYSTEM = (
    "Sen bir finansal analiz iş akışında araç çağrısı planlayıcısısın. Yalnızca verilen izinli araçları, verilen JSON "
    "şemasına uygun argümanlarla çağır. Her çağrıda as_of_date zorunludur ve soru tarihine eşittir. Sayı uydurma, "
    "yorum yazma; yalnızca tool_calls JSON'u döndür."
)


def _compact_schema(tool: str) -> dict[str, str]:
    """field -> short type text (required fields marked with '*'); keeps planning prompts small."""
    schema = REGISTRY[tool].input_model.model_json_schema()
    req = set(schema.get("required", []))
    out = {}
    for name, prop in schema.get("properties", {}).items():
        t = prop.get("type") or "/".join(
            str(x.get("type", x.get("$ref", "obj")).split("/")[-1]) for x in prop.get("anyOf", [])
        )
        out[name + ("*" if name in req else "")] = str(t or "object")
    return out


def planner_schema(allowed: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "tool_calls": {
                "type": "array",
                "maxItems": 12,  # bounds decoding loops; the largest state (10 stock histories + index) needs 11
                "items": {
                    "type": "object",
                    "properties": {"tool": {"type": "string", "enum": allowed}, "arguments": {"type": "object"}},
                    "required": ["tool", "arguments"],
                },
            }
        },
        "required": ["tool_calls"],
    }


def planner_messages(
    state: HarnessState, req: AnalysisRequest, done: list[dict[str, Any]], allowed: list[str]
) -> list[dict[str, str]]:
    user = {
        "state": state.value,
        "question": req.question,
        "scenario": req.scenario.value,
        "tickers": req.tickers,
        "params": req.params,
        "as_of_date": req.as_of_date.isoformat(),
        "analysis_start": req.start.isoformat(),
        "allowed_tools": {t: _compact_schema(t) for t in allowed},
        "already_called": [d["tool"] for d in done][-12:],
    }
    return [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
    ]


def parse_tool_calls(text: str) -> list[ToolCall]:
    try:
        data = json.loads(text)
        items = data.get("tool_calls", []) if isinstance(data, dict) else []
    except json.JSONDecodeError:
        items = []
    return [
        ToolCall(it["tool"], dict(it["arguments"]), origin="llm")
        for it in items
        if isinstance(it, dict) and isinstance(it.get("tool"), str) and isinstance(it.get("arguments"), dict)
    ]


@dataclass
class LLMPlanner:
    client: LLMClient
    policy: Policy
    name: str = "llm_planner_v1"
    # LLM calls made since the last drain(); the runner moves them into the episodic memory after every state
    pending: list[PlannerCall] = field(default_factory=list)

    def propose(self, state: HarnessState, req: AnalysisRequest, done: list[dict[str, Any]]) -> list[ToolCall]:
        allowed = sorted(self.policy.permissions[state])
        if not allowed or state in HARNESS_BUILT:
            return []
        messages = planner_messages(state, req, done, allowed)
        resp = self.client.chat(messages, planner_schema(allowed))
        calls = parse_tool_calls(resp.text)
        self.pending.append(PlannerCall(state.value, messages, resp, len(calls)))
        return calls

    def drain(self) -> list[PlannerCall]:
        out, self.pending = self.pending, []
        return out


@dataclass(frozen=True)
class PlannerCall:
    state: str
    messages: list[dict[str, str]]
    response: LLMResponse
    n_proposed: int
