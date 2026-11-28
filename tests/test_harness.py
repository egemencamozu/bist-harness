"""The stateful harness on the synthetic snapshot: policy, question parsing, validator, state machine, LLM retry /
fallback, invalid tool calls, safety refusal, episodic memory and replay."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator, Sequence
from datetime import date
from typing import Any

import pytest

from bistharness.core.config import load_universe, project_root, read_config_yaml
from bistharness.core.enums import AnalyticalAction, GateStatus, HarnessState, ReviewVerdict, Scenario, StateStatus
from bistharness.core.errors import ConfigError
from bistharness.harness.explainer import LLMExplainer, TemplateExplainer
from bistharness.harness.llm_client import OllamaClient, ScriptedClient
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.planner import LLMPlanner, ScenarioPlanner, ToolCall
from bistharness.harness.policy import load_policy, policy_from_dict
from bistharness.harness.replay import replay_analysis
from bistharness.harness.request import AnalysisRequest, QuestionParseError, parse_question
from bistharness.harness.runner import AnalysisResult, HarnessConfig, Review, run_analysis
from bistharness.harness.validator import validate
from bistharness.tools import ToolContext
from tests.test_tools import _ctx

AS_OF = date(2026, 9, 10)
POLICY = load_policy()
RULES = POLICY.validation


@pytest.fixture(scope="module")
def ctx() -> Iterator[ToolContext]:
    yield _ctx(False)


def _req(scenario: Scenario, tickers: list[str], question: str = "test sorusu", **kw: Any) -> AnalysisRequest:
    return AnalysisRequest(
        question=question, scenario=scenario, tickers=tickers, as_of_date=AS_OF, start=date(2025, 1, 1), **kw
    )


@pytest.fixture(scope="module")
def s3(ctx: ToolContext) -> tuple[AnalysisResult, EpisodicMemory]:
    mem = EpisodicMemory()
    res = run_analysis(
        _req(Scenario.S3_TECHNICAL_REVERSAL, ["ASELS"]),
        ctx,
        HarnessConfig(ScenarioPlanner(POLICY), TemplateExplainer(POLICY), mem),
    )
    return res, mem


# ----------------------------------------------------------------------------------------------- policy & parsing
def test_policy_guards() -> None:
    raw = read_config_yaml("harness_policy.yaml")
    bad = copy.deepcopy(raw)
    bad["not_applicable"]["S3_TECHNICAL_REVERSAL"]["RUN_BACKTEST"] = "skip it"
    with pytest.raises(ConfigError, match="mandatory"):
        policy_from_dict(bad)
    bad = copy.deepcopy(raw)
    bad["states"] = list(reversed(bad["states"]))
    with pytest.raises(ConfigError, match="fixed order"):
        policy_from_dict(bad)
    bad = copy.deepcopy(raw)
    bad["permissions"]["LOAD_MARKET_DATA"].append("place_order")
    with pytest.raises(ConfigError, match="unknown tools"):
        policy_from_dict(bad)


def test_parse_golden_questions() -> None:
    g = json.loads((project_root() / "eval" / "golden_questions.json").read_text("utf-8"))
    u = load_universe()
    for q in g["questions"]:
        r = parse_question(q["question"], as_of=AS_OF, universe=u)
        assert (r.scenario.value, r.tickers) == (q["scenario"], q["tickers"]), q["id"]
    assert parse_question("EREGL hedef fiyat kaç?", as_of=AS_OF, universe=u).advice_requested
    with pytest.raises(QuestionParseError):
        parse_question("Borsa bugün nasıl?", as_of=AS_OF, universe=u)


# ----------------------------------------------------------------------------------------------- validator
COMMITTED = [
    {"id": "E1", "key": "reversal.ASELS.BB_LOWER_TOUCH.h5", "claim_tr": "…", "kind": "statistic"},
    {"id": "E2", "key": "backtest.A_TECH", "claim_tr": "…", "kind": "statistic"},
]
NUMS = [73.53, 34.0, 25.0, 5.0, 56.24]
DATES = ["01.01.2024", "10.09.2026"]


def _v(out: dict[str, Any], gate: GateStatus = GateStatus.PASS, advice: bool = False) -> Any:
    return validate(
        out,
        committed=COMMITTED,
        allowed_numbers=NUMS,
        allowed_dates=DATES,
        gate=gate,
        rules=RULES,
        as_of=AS_OF,
        advice_requested=advice,
    )


def _out(
    text: str, action: str = "WATCH", cited: Sequence[str] = ("E1",), refusal: bool = False, lim: str = ""
) -> dict[str, Any]:
    return {
        "action": action,
        "explanation_tr": text,
        "cited_evidence": list(cited),
        "refusal_needed": refusal,
        "limitations_tr": lim,
    }


OK_TEXT = "Alt Bollinger dokunuşu 34 kez oluştu ve 25 tanesinde 5 gün sonra yükseliş görüldü (%73,53) (E1)."


@pytest.mark.parametrize(
    ("out", "gate", "advice", "fails"),
    [
        (_out(OK_TEXT), GateStatus.PASS, False, None),
        (_out(OK_TEXT + " Satın alma gücü değişti (E1)."), GateStatus.PASS, False, None),  # allowed phrase
        (_out(OK_TEXT.replace("%73,53", "%73,5")), GateStatus.PASS, False, "numbers"),  # rounded = invented
        (_out(OK_TEXT + " 2025 yılında da (E1)."), GateStatus.PASS, False, "numbers"),
        (_out(OK_TEXT + " 05.05.2025 tarihinde (E1)."), GateStatus.PASS, False, "dates"),
        (_out(OK_TEXT + " Hedef fiyat yoktur."), GateStatus.PASS, False, "forbidden"),
        (_out(OK_TEXT + " Hemen alın."), GateStatus.PASS, False, "forbidden"),
        (_out(OK_TEXT + " Hisse kesin yükselir."), GateStatus.PASS, False, "forbidden"),
        (_out(OK_TEXT, cited=("E7",)), GateStatus.PASS, False, "citations_exist"),
        (_out(OK_TEXT.replace(" (E1)", ""), cited=()), GateStatus.PASS, False, "has_citation"),
        (_out(OK_TEXT, action="TECHNICAL_REVERSAL_CANDIDATE"), GateStatus.PASS, False, "candidate_backtest"),
        (_out(OK_TEXT, action="TECHNICAL_REVERSAL_CANDIDATE", cited=("E1", "E2")), GateStatus.PASS, False, None),
        (
            _out(OK_TEXT, action="TECHNICAL_REVERSAL_CANDIDATE", cited=("E1", "E2")),
            GateStatus.INVESTIGATE,
            False,
            "action_allowed",
        ),
        (_out(OK_TEXT), GateStatus.PASS, True, "refusal"),
        (_out(OK_TEXT, refusal=True), GateStatus.PASS, True, None),
    ],
)
def test_validator(out: dict[str, Any], gate: GateStatus, advice: bool, fails: str | None) -> None:
    r = _v(out, gate, advice)
    if fails is None:
        assert r.ok, r.errors
    else:
        assert not r.ok and r.checks[fails] is False, r.errors


def test_validator_rejects_bad_json_and_ignores_evidence_ids_as_numbers() -> None:
    assert not _v("{not json").ok  # type: ignore[arg-type]
    r = _v(_out("Kanıt E1 ve E2 birlikte değerlendirildi; sayı yok (E1).", cited=("E1", "E2")))
    assert r.ok, r.errors


# ----------------------------------------------------------------------------------------------- state machine
def test_states_run_in_order_with_skips_and_mandatory_states(s3: tuple[AnalysisResult, EpisodicMemory]) -> None:
    res, mem = s3
    assert [s.state for s in res.states] == list(HarnessState)
    status = {s.state: s.status for s in res.states}
    for m in POLICY.mandatory:
        assert status[m] is StateStatus.DONE
    for st in POLICY.not_applicable[Scenario.S3_TECHNICAL_REVERSAL]:
        assert status[st] is StateStatus.SKIPPED_NOT_APPLICABLE
    assert res.invalid_calls == []
    keys = [c["key"] for c in res.bundle["committed"]]
    assert keys[-1] == "gate.result" and "backtest.A_TECH" in keys and "reversal.ASELS.BB_LOWER_TOUCH.h5" in keys
    assert res.explanation is not None and not res.explanation.fallback_used
    assert [s["state"] for s in mem.states(res.analysis_id)] == [s.value for s in HarnessState]
    assert mem.decision(res.decision_id or "")["action"] == res.explanation.action.value


def test_replay_reproduces_every_tool_call(ctx: ToolContext, s3: tuple[AnalysisResult, EpisodicMemory]) -> None:
    res, mem = s3
    rep = replay_analysis(res.decision_id or "", ctx, mem)
    assert rep.calls and rep.tools_match, [c for c in rep.calls if not c.match]


def test_human_review_is_recorded(s3: tuple[AnalysisResult, EpisodicMemory]) -> None:
    res, mem = s3
    did = res.decision_id or ""
    with pytest.raises(ValueError):
        mem.add_review(did, reviewer="r", verdict="REJECT", reason="  ")
    mem.add_review(did, reviewer="r", verdict="REJECT", reason="tarihsel düşüş çok yüksek")
    assert mem.reviews(did)[0]["verdict"] == "REJECT"


class _BadPlanner:
    """Proposes a forbidden tool, a wrong as_of and a malformed call; no backtest (mandatory)."""

    name = "bad"

    def propose(self, state: HarnessState, req: AnalysisRequest, done: list[dict[str, Any]]) -> list[ToolCall]:
        if state is HarnessState.LOAD_MARKET_DATA:
            return [
                ToolCall("run_backtest", {"as_of_date": "2026-09-10"}, "llm"),
                ToolCall("get_stock_history", {"as_of_date": "2026-12-31", "ticker": "THYAO"}, "llm"),
                ToolCall("get_stock_history", {"as_of_date": "2026-09-10", "ticker": "THYAO", "foo": 1}, "llm"),
                ToolCall("get_stock_history", {"as_of_date": "2026-09-10", "ticker": "THYAO"}, "llm"),
            ]
        if state is HarnessState.RUN_PATTERN_AND_REVERSAL_ANALYSIS:
            return ScenarioPlanner(POLICY).propose(state, req, done)
        return []


def test_invalid_calls_are_logged_and_mandatory_backtest_falls_back(ctx: ToolContext) -> None:
    mem = EpisodicMemory()
    res = run_analysis(
        _req(Scenario.S2_WEEKDAY_PATTERN, ["THYAO"]), ctx, HarnessConfig(_BadPlanner(), TemplateExplainer(POLICY), mem)
    )
    errors = [c.error or "" for c in res.invalid_calls]
    assert len(errors) == 3
    assert "not permitted in LOAD_MARKET_DATA" in errors[0] and "as_of_date must be" in errors[1]
    assert "invalid input" in errors[2]
    bt = [c for c in res.calls if c.state is HarnessState.RUN_BACKTEST and c.tool == "run_backtest"]
    assert bt and bt[0].origin == "harness_default" and bt[0].valid
    rows = mem.tool_calls(res.analysis_id)
    assert sum(1 for r in rows if not r["valid"]) == 3


def test_llm_planner_calls_are_logged_in_episodic_memory(ctx: ToolContext) -> None:
    """A scripted 'model' proposes the default plan; every planner prompt + raw answer is stored as plan:<state>."""
    req = _req(Scenario.S3_TECHNICAL_REVERSAL, ["ASELS"])
    default = ScenarioPlanner(POLICY)

    def answer(messages: Sequence[dict[str, str]]) -> str:
        state = HarnessState(json.loads(messages[-1]["content"])["state"])
        calls = default.propose(state, req, [])
        return json.dumps({"tool_calls": [{"tool": c.tool, "arguments": c.arguments} for c in calls]})

    mem = EpisodicMemory()
    planner = LLMPlanner(ScriptedClient(fn=answer), POLICY)
    res = run_analysis(req, ctx, HarnessConfig(planner, TemplateExplainer(POLICY), mem))
    assert not res.invalid_calls and all(c.origin != "harness_default" for c in res.calls)
    plans = [r for r in mem.llm_calls(res.analysis_id) if r["purpose"].startswith("plan:")]
    planned_states = {s.state.value for s in res.states if any(c.origin == "llm" for c in s.calls)}
    assert {r["purpose"][5:] for r in plans} >= planned_states and plans
    assert all(r["prompt_hash"] and r["raw_output"].startswith('{"tool_calls"') for r in plans)
    assert planner.pending == []  # drained into memory, nothing accumulates across analyses


# ----------------------------------------------------------------------------------------------- LLM explainer
def _first_claim_number(res: AnalysisResult) -> str:
    c = res.bundle["committed"][0]
    return next(v for v in c["display"].values() if any(ch.isdigit() for ch in v))


def test_llm_retry_then_accept_and_double_failure_falls_back(s3: tuple[AnalysisResult, EpisodicMemory]) -> None:
    res, _ = s3
    good = json.dumps(
        {
            "action": "WATCH",
            "explanation_tr": f"Olay istatistiği {_first_claim_number(res)} (E1).",
            "cited_evidence": ["E1"],
            "refusal_needed": False,
            "limitations_tr": "",
        },
        ensure_ascii=False,
    )
    bad = json.dumps(
        {
            "action": "WATCH",
            "explanation_tr": "Getiri %99,99 oldu, hedef fiyat yükselir (E1).",
            "cited_evidence": ["E1"],
            "refusal_needed": False,
            "limitations_tr": "",
        },
        ensure_ascii=False,
    )
    client = ScriptedClient([bad, good])
    e = LLMExplainer(client, POLICY).explain(res.request, res.bundle, res.gate)
    assert len(e.attempts) == 2 and not e.attempts[0].validation.ok and e.attempts[1].validation.ok
    assert e.action is AnalyticalAction.WATCH and not e.fallback_used
    assert "Cevabın denetimden geçmedi" in client.calls[1][-1]["content"]  # error feedback reached the model
    e2 = LLMExplainer(ScriptedClient([bad, bad]), POLICY).explain(res.request, res.bundle, res.gate)
    assert e2.fallback_used and e2.action is AnalyticalAction.ANALYSIS_UNSAFE and e2.teacher_action is not None


def test_safety_request_gets_refusal_and_cautious_action(ctx: ToolContext) -> None:
    req = _req(
        Scenario.SAFETY_ADVICE_REQUEST,
        ["THYAO"],
        question="THYAO kesin yükselir, alayım mı? Hedef fiyat ver.",
        advice_requested=True,
    )
    res = run_analysis(
        req,
        ctx,
        HarnessConfig(
            ScenarioPlanner(POLICY),
            TemplateExplainer(POLICY),
            EpisodicMemory(),
            reviewer=lambda r: Review(ReviewVerdict.ACCEPT, "ret doğru"),
        ),
    )
    assert res.explanation is not None
    assert res.explanation.action in {AnalyticalAction.WATCH, AnalyticalAction.INVESTIGATE}
    assert res.explanation.text_tr.startswith(RULES.refusal_template)
    assert res.review is not None and res.review.verdict is ReviewVerdict.ACCEPT


def test_ollama_client_refuses_remote_hosts() -> None:
    with pytest.raises(ConfigError, match="not local"):
        OllamaClient("qwen2.5:7b", host="https://api.example.com")


def test_ollama_abort_on_repetition_is_an_invalid_answer_not_a_crash() -> None:
    import ollama

    class _Server:
        def generate(self, **_: Any) -> None:
            return None

        def chat(self, **_: Any) -> None:
            raise ollama.ResponseError("prediction aborted, token repeat limit reached", 500)

    c = OllamaClient("bist-analist")
    c._client, c._digest = _Server(), "sha"  # type: ignore[assignment]
    r = c.chat([{"role": "user", "content": "x"}], {"type": "object"})
    assert r.text == "" and r.error and "repeat limit" in r.error
    # the explainer then retries and finally falls back to the safe template
    req = _req(Scenario.S3_TECHNICAL_REVERSAL, ["ASELS"])
    bundle = {"committed": [], "allowed_numbers": [], "allowed_dates": []}
    e = LLMExplainer(c, POLICY).explain(req, bundle, GateStatus.PASS)
    assert e.fallback_used and e.action is AnalyticalAction.ANALYSIS_UNSAFE

    class _Down(_Server):
        def chat(self, **_: Any) -> None:
            raise ollama.ResponseError("model not found", 404)

    c._client = _Down()  # type: ignore[assignment]
    with pytest.raises(ollama.ResponseError):  # other server errors still surface
        c.chat([{"role": "user", "content": "x"}], {"type": "object"})


def test_validator_checks_the_kind_of_number_and_accepts_years_of_committed_dates() -> None:
    committed = [
        {
            "id": "E1",
            "key": "sector.G.catch_up.h20",
            "kind": "statistic",
            "claim_tr": "01.01.2024–10.09.2026 arasında 66 girişin 37 tanesinde (%56,06); 31 yanlış pozitif.",
            "display": {"s": "01.01.2024", "e": "10.09.2026", "n": "66", "k": "37", "rate": "%56,06", "fp": "31"},
        }
    ]

    def run(text: str) -> Any:
        return validate(
            _out(text),
            committed=committed,
            allowed_numbers=[66, 37, 56.06, 31],
            allowed_dates=["01.01.2024", "10.09.2026"],
            gate=GateStatus.PASS,
            rules=RULES,
            as_of=AS_OF,
            advice_requested=False,
        )

    assert run("2024 ile 2026 arasında 66 girişin %56,06'sı başarılı, 31 yanlış pozitif (E1).").ok
    bad = run("66 girişin %56,06'sı başarılı ve %31 yanlış pozitif (E1).")
    assert not bad.ok and bad.bad_numbers == [31.0]
    assert not run("2019 yılından beri 66 giriş (E1).").ok


# ----------------------------------------------------------------------------------------------- S1 sector = peer group
def test_sector_comparison_uses_the_whole_peer_group() -> None:
    from bistharness.harness.planner import canonical_sector_calls, sector_groups

    u = load_universe()
    assert sector_groups(["MGROS", "SOKM"], u) == ["Perakende"]
    assert sector_groups(["BIMAS", "THYAO", "MGROS"], u) == ["Perakende", "Havacilik_Lojistik"]
    model = [
        ToolCall("rank_sector_relative_strength", {"sector_or_tickers": ["MGROS", "SOKM"], "horizon": 20}, "llm"),
        ToolCall("rank_sector_relative_strength", {"sector_or_tickers": "Perakende"}, "llm"),
        ToolCall("rank_sector_relative_strength", {"sector_or_tickers": ["NOPE1", "NOPE2"]}, "llm"),
        ToolCall("get_index_history", {}, "llm"),
    ]
    out = canonical_sector_calls(model, u)
    assert out[0] == ToolCall("rank_sector_relative_strength", {"sector_or_tickers": "Perakende", "horizon": 20}, "llm")
    assert out[1:] == model[1:]  # group names, unknown tickers (rejected later by the tool) and other tools unchanged
    calls = ScenarioPlanner(POLICY).propose(
        HarnessState.RUN_SECTOR_RELATIVE_ANALYSIS, _req(Scenario.S1_SECTOR_CATCH_UP, ["MGROS", "SOKM"]), []
    )
    assert [c.arguments["sector_or_tickers"] for c in calls] == ["Perakende"]
