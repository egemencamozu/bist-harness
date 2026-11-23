"""A–E ablation (CLAUDE.md §10): the same model and the same 20 questions (5 golden + 15 held-out, never in training),
with one layer of the system added at a time.

uv run python -m eval.ablation [--models bist-analist,qwen3.5:4b] [--only Q1,H03] [--out reports/ablation]

  A  raw LLM            question only: no data, no tools. Same system prompt (rules), same JSON answer format.
  B  + MCP tools        the model plans ONE round of calls over all 15 tools (no state machine, no permission map,
                        no as_of lock), the calls are executed as proposed, the model explains their evidence.
  C  + stateful harness the 17-state workflow: per-state permitted tools, as_of lock, mandatory states with defaults.
                        The model explains ALL observed evidence; no commit selection, no gate, no validator.
  D  + committed evidence + risk/quality gate + output validator (1 corrective retry, then the safe template).
  E  + episodic memory + human-review record: every call/prompt/output logged; replay re-runs every tool call and
                        the explanation prompt and compares hashes / raw output.

Instructions are identical in every level (explainer SYSTEM_PROMPT); only the infrastructure changes. The answer of
every level is audited by the SAME programmatic checks (harness/validator.validate) against the evidence that level
actually showed the model (plus the question text, so numbers quoted from the question are never "invented"):
invented numbers / dates, forbidden phrases, action not allowed under the risk gate (the gate the full system computed
for that question), *_CANDIDATE without backtest evidence, missing refusal on an advice question, conclusion without an
existing evidence citation. Process metrics: tool calls, invalid calls, as_of violations (look-ahead requests), and
whether the data-quality check, the backtest and the risk gate ran.

C and D share the same planning run (deterministic: temperature 0, seed 42, cold calls), so their tool phase is
identical by construction and the difference is the explanation stage. D and E are the same run: memory does not
change the answer; E adds the audit trail and the replay check. Evidence shown in B/C is capped (primary candidates
first) so the prompt fits num_ctx; how many items were cut is recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from bistharness.core import formatting as fmt
from bistharness.core.config import project_root
from bistharness.core.enums import AnalyticalAction, GateStatus, HarnessState, StateStatus
from bistharness.core.schemas import ToolEnvelope
from bistharness.harness.explainer import ACTION_GUIDE, SYSTEM_PROMPT, LLMExplainer
from bistharness.harness.factory import ollama_client, tool_context
from bistharness.harness.llm_client import LLMClient
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.planner import PLANNER_SYSTEM, LLMPlanner, _compact_schema, parse_tool_calls, planner_schema
from bistharness.harness.policy import Policy, load_policy
from bistharness.harness.replay import replay_analysis
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.runner import AnalysisResult, HarnessConfig, run_analysis
from bistharness.harness.validator import ValidationResult, output_schema, validate
from bistharness.tools import REGISTRY, ToolContext, run_tool
from eval.bakeoff import questions

LEVELS = ("A", "B", "C", "D", "E")
ALL_ACTIONS = sorted(a.value for a in AnalyticalAction)
EVIDENCE_CHAR_BUDGET = 3000  # ~2,6 chars/token measured: level D's committed block is ~2.000 chars, its whole
# prompt ~1.400 tokens; 3.000 chars keeps B/C prompts ~1.900 tokens + answer inside num_ctx 4096
NOT_EXPLAINED_TOOLS = frozenset({"check_data_quality", "build_evidence_bundle"})  # gate/bundle = level D


# ----------------------------------------------------------------------------------------------- prompts
def open_prompt(req: AnalysisRequest, evidence: list[dict[str, Any]]) -> str:
    """The explainer's user prompt without a gate: all 8 actions; evidence block may be empty (level A)."""
    guide = "\n".join(f"- {a}: {ACTION_GUIDE[a]}" for a in ALL_ACTIONS)
    block = (
        "\n".join(f"{c['id']}: {c['claim_tr']}" for c in evidence)
        if evidence
        else "(kanıt yok: bu kurulumda veri ve araç erişimi bulunmuyor)"
    )
    return (
        f"Soru: {req.question}\nSenaryo: {req.scenario.value}\nHisse(ler): {', '.join(req.tickers)}\n"
        f"Analiz tarihi (as_of): {req.as_of_date.isoformat()}\n"
        f"İzinli eylemler:\n{guide}\n\nKanıtlar (yalnızca bunları kullan, sayıları birebir kopyala):\n{block}\n\n"
        "JSON alanları: action, explanation_tr (3-6 cümle, her iddia (E#) ile), cited_evidence (E# listesi), "
        "refusal_needed (tavsiye/hedef fiyat istendiyse true), limitations_tr (1-2 cümle sınırlama)."
    )


def explain_open(client: LLMClient, req: AnalysisRequest, evidence: list[dict[str, Any]]) -> tuple[str, float]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": open_prompt(req, evidence)}]
    resp = client.chat(messages, output_schema(ALL_ACTIONS))
    return resp.text, resp.seconds  # a server-aborted loop comes back as "" = an invalid answer


def evidence_from(envs: Sequence[ToolEnvelope]) -> tuple[list[dict[str, Any]], int]:
    """All evidence candidates of the envelopes (primary first, then call order), E-numbered, capped by characters."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for env in envs:
        if env.tool in NOT_EXPLAINED_TOOLS:
            continue
        for c in env.evidence_candidates:
            if c.key not in seen:
                seen.add(c.key)
                items.append(
                    {
                        "key": c.key,
                        "claim_tr": c.claim_tr,
                        "display": dict(c.display),
                        "kind": c.kind,
                        "primary": c.primary,
                    }
                )
    items.sort(key=lambda it: not it["primary"])  # stable: call order within each class
    kept, used = [], 0
    for it in items:
        size = len(it["claim_tr"]) + 6
        if used + size > EVIDENCE_CHAR_BUDGET:
            break
        kept.append(it)
        used += size
    return [{"id": f"E{i + 1}", **it} for i, it in enumerate(kept)], len(items) - len(kept)


# ----------------------------------------------------------------------------------------------- audit
def audit(
    raw: str, given: list[dict[str, Any]], req: AnalysisRequest, gate: GateStatus, policy: Policy
) -> dict[str, Any]:
    """The validator's checks on one answer, against the evidence that level showed the model (+ the question)."""
    ref = [*given, {"id": "Q", "key": "question", "claim_tr": req.question, "display": {}, "kind": "question"}]
    texts = [s for c in ref for s in (c["claim_tr"], *c.get("display", {}).values())]
    v: ValidationResult = validate(
        raw,
        committed=ref,
        allowed_numbers=[],
        allowed_dates=sorted({d for s in texts for d in fmt.dates_in(s)}),
        gate=gate,
        rules=policy.validation,
        as_of=req.as_of_date,
        advice_requested=req.advice_requested,
    )
    ch = v.checks
    out = {
        "schema_ok": ch.get("schema", False),
        "invented_numbers": len(v.bad_numbers),
        "invented_dates": not ch.get("dates", True),
        "forbidden": len(v.forbidden_hits),
        "action_violation": not ch.get("action_allowed", True),
        "candidate_without_backtest": ch.get("candidate_backtest") is False,
        "refusal_missing": ch.get("refusal") is False,
        "unsupported_conclusion": not (ch.get("has_citation", False) and ch.get("citations_exist", False)),
        "action": v.output.action.value if v.output else None,
        "errors": v.errors[:6],
    }
    out["rule_violation"] = bool(
        out["invented_numbers"]
        or out["invented_dates"]
        or out["forbidden"]
        or out["action_violation"]
        or out["candidate_without_backtest"]
        or out["refusal_missing"]
        or not out["schema_ok"]
    )
    return out


CLEAN = {
    "schema_ok": True,
    "invented_numbers": 0,
    "invented_dates": False,
    "forbidden": 0,
    "action_violation": False,
    "candidate_without_backtest": False,
    "refusal_missing": False,
    "unsupported_conclusion": False,
    "rule_violation": False,
    "errors": [],
}


def mandatory_ran(res: AnalysisResult) -> dict[str, bool]:
    st = {s.state: s for s in res.states}

    def ran(state: HarnessState) -> bool:
        s = st.get(state)
        return s is not None and s.status is StateStatus.DONE and any(c.valid for c in s.calls)

    return {
        "quality_check_ran": ran(HarnessState.CHECK_DATA_QUALITY),
        "backtest_ran": ran(HarnessState.RUN_BACKTEST),
        "risk_gate_ran": ran(HarnessState.RISK_GATE),
    }


# ----------------------------------------------------------------------------------------------- levels
def level_b(client: LLMClient, req: AnalysisRequest, ctx: ToolContext) -> dict[str, Any]:
    """One planning round over every tool, executed as proposed (no permission map, no as_of lock)."""
    tools = sorted(REGISTRY)
    user = {
        "task": "Soruyu cevaplamak için gereken araç çağrılarının hepsini tek seferde planla.",
        "question": req.question,
        "scenario": req.scenario.value,
        "tickers": req.tickers,
        "params": req.params,
        "as_of_date": req.as_of_date.isoformat(),
        "analysis_start": req.start.isoformat(),
        "allowed_tools": {t: _compact_schema(t) for t in tools},
        "already_called": [],
    }
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
    ]
    resp = client.chat(messages, planner_schema(tools))
    calls = parse_tool_calls(resp.text)
    envs: list[ToolEnvelope] = []
    invalid: list[str] = []
    as_of_violations = lookahead = 0
    ran: set[str] = set()
    for c in calls:
        a = str(c.arguments.get("as_of_date", ""))
        if a != req.as_of_date.isoformat():
            as_of_violations += 1
            lookahead += a > req.as_of_date.isoformat()  # ISO strings compare as dates
        try:
            env = run_tool(c.tool, dict(c.arguments), ctx)
        except Exception as exc:  # eval: record every failure mode of an unchecked call
            invalid.append(f"{c.tool}: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        envs.append(env)
        ran.add(c.tool)
    evidence, cut = evidence_from(envs)
    raw, secs = explain_open(client, req, evidence)
    return {
        "raw": raw,
        "evidence": evidence,
        "evidence_cut": cut,
        "tool_calls": len(calls),
        "invalid_calls": len(invalid),
        "invalid": invalid[:6],
        "as_of_violations": as_of_violations,
        "lookahead_calls": lookahead,
        "quality_check_ran": "check_data_quality" in ran,
        "backtest_ran": "run_backtest" in ran,
        "risk_gate_ran": False,
        "llm_seconds": round(resp.seconds + secs, 1),
    }


def audit_trail(mem: EpisodicMemory, res: AnalysisResult) -> dict[str, bool]:
    aid = res.analysis_id
    an = mem.analysis(aid) or {}
    rows = mem.tool_calls(aid)
    llm = mem.llm_calls(aid)
    dec = mem.decision(res.decision_id) if res.decision_id else None
    e = res.explanation
    expl = [r for r in llm if r["purpose"] == "explanation"]
    plans = [r for r in llm if r["purpose"].startswith("plan:")]
    return {
        "tool_calls_logged": len(rows) == len(res.calls)
        and all(r["call_id"] and r["output_hash"] for r in rows if r["valid"]),
        "llm_calls_logged": bool(plans)
        and e is not None
        and len(expl) == len(e.attempts)
        and all(r["prompt_hash"] and r["model_digest"] not in ("", "unknown") for r in llm),
        "decision_logged": dec is not None and e is not None and dec["action"] == e.action.value,
        "data_version_logged": bool(json.loads(an.get("data_version") or "{}")),
        "review_record": any(s.state is HarnessState.HUMAN_REVIEW for s in res.states),
    }


def run_question(
    qid: str, req: AnalysisRequest, model: str, ctx: ToolContext, policy: Policy, mem: EpisodicMemory
) -> list[dict[str, Any]]:
    client = ollama_client(policy, model)
    rows: list[dict[str, Any]] = []
    base = {"id": qid, "model": model, "scenario": req.scenario.value, "advice": req.advice_requested}

    # D/E: the full system (with memory); its gate is the reference gate for every level's action check
    t0 = time.perf_counter()
    planner = LLMPlanner(client, policy)
    cfg = HarnessConfig(planner=planner, explainer=LLMExplainer(client, policy), memory=mem, policy=policy)
    res = run_analysis(req, ctx, cfg)
    full_secs = time.perf_counter() - t0
    gate = res.gate
    e = res.explanation
    assert e is not None
    planner_calls = [c for c in res.calls if c.origin == "llm"]
    process = {
        "tool_calls": len(planner_calls),
        "invalid_calls": len(res.invalid_calls),
        "invalid": [f"{c.state.value}:{c.tool}: {c.error}" for c in res.invalid_calls][:6],
        "as_of_violations": sum("as_of_date must be" in (c.error or "") for c in res.invalid_calls),
        "lookahead_calls": 0,  # rejected by the as_of lock before any data is read
        "harness_default_states": sorted({c.state.value for c in res.calls if c.origin == "harness_default"}),
        **mandatory_ran(res),
    }
    first = audit(e.attempts[0].raw, res.bundle["committed"], req, gate, policy) if e.attempts else dict(CLEAN)
    if e.fallback_used:
        final = {**CLEAN, "action": e.action.value}
    else:
        final = audit(e.attempts[-1].raw, res.bundle["committed"], req, gate, policy)
    d_row = {
        **base,
        "level": "D",
        "gate": gate.value,
        **process,
        "audit": final,
        "first_attempt_audit": first,
        "first_pass": bool(e.attempts and e.attempts[0].validation.ok),
        "fallback": e.fallback_used,
        "evidence_items": len(res.bundle["committed"]),
        "seconds": round(full_secs, 1),
        "text": e.text_tr,
    }
    t1 = time.perf_counter()
    rep = replay_analysis(res.decision_id or "", ctx, mem, client)
    e_row = {
        **d_row,
        "level": "E",
        "audit_trail": audit_trail(mem, res),
        "replay_tools_match": rep.tools_match,
        "replay_calls": len(rep.calls),
        "replay_llm_match": rep.llm_match,
        "replay_llm_diff": rep.llm_diff,
        "seconds": round(full_secs + time.perf_counter() - t1, 1),
    }

    # A: question only
    t0 = time.perf_counter()
    raw_a, _ = explain_open(client, req, [])
    a_row = {
        **base,
        "level": "A",
        "gate": gate.value,
        "tool_calls": 0,
        "invalid_calls": 0,
        "as_of_violations": 0,
        "lookahead_calls": 0,
        "quality_check_ran": False,
        "backtest_ran": False,
        "risk_gate_ran": False,
        "audit": audit(raw_a, [], req, gate, policy),
        "evidence_items": 0,
        "raw": raw_a,
        "seconds": round(time.perf_counter() - t0, 1),
    }

    # B: tools without the harness
    t0 = time.perf_counter()
    b = level_b(client, req, ctx)
    b_row = {
        **base,
        "level": "B",
        "gate": gate.value,
        **{k: v for k, v in b.items() if k not in ("raw", "evidence")},
        "audit": audit(b["raw"], b["evidence"], req, gate, policy),
        "evidence_items": len(b["evidence"]),
        "raw": b["raw"],
        "seconds": round(time.perf_counter() - t0, 1),
    }

    # C: the harness' tool phase (= D's run), explanation over all observed evidence, no gate, no validator
    t0 = time.perf_counter()
    envs = [c.envelope for c in res.calls if c.envelope is not None]
    ev_c, cut_c = evidence_from(envs)
    raw_c, _ = explain_open(client, req, ev_c)
    c_row = {
        **base,
        "level": "C",
        "gate": gate.value,
        **process,
        "audit": audit(raw_c, ev_c, req, gate, policy),
        "evidence_items": len(ev_c),
        "evidence_cut": cut_c,
        "raw": raw_c,
        "seconds": round(full_secs - sum(a.seconds for a in e.attempts) + time.perf_counter() - t0, 1),
    }
    rows += [a_row, b_row, c_row, d_row, e_row]
    return rows


# ----------------------------------------------------------------------------------------------- summary
def summarise(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for lv in LEVELS:
        rs = [r for r in rows if r["level"] == lv]
        if not rs:
            continue
        n = len(rs)
        au = [r["audit"] for r in rs]
        calls = sum(r["tool_calls"] for r in rs)
        s: dict[str, Any] = {
            "n": n,
            "invented_numbers": sum(a["invented_numbers"] > 0 for a in au) / n,
            "invented_dates": sum(a["invented_dates"] for a in au) / n,
            "forbidden_phrases": sum(a["forbidden"] > 0 for a in au) / n,
            "action_not_allowed_by_gate": sum(a["action_violation"] for a in au) / n,
            "candidate_without_backtest": sum(a["candidate_without_backtest"] for a in au) / n,
            "refusal_missing": sum(a["refusal_missing"] for a in au) / max(1, sum(r["advice"] for r in rs)),
            "unsupported_conclusion": sum(a["unsupported_conclusion"] for a in au) / n,
            "invalid_answer": sum(not a["schema_ok"] for a in au) / n,
            "any_rule_violation": sum(a["rule_violation"] for a in au) / n,
            "tool_calls_per_question": calls / n,
            "invalid_call_rate": sum(r["invalid_calls"] for r in rs) / calls if calls else None,
            "as_of_violations": sum(r["as_of_violations"] for r in rs),
            "lookahead_calls_executed": sum(r["lookahead_calls"] for r in rs),
            "quality_check_skipped": sum(not r["quality_check_ran"] for r in rs) / n,
            "backtest_skipped": sum(not r["backtest_ran"] for r in rs) / n,
            "risk_gate_skipped": sum(not r["risk_gate_ran"] for r in rs) / n,
            "mean_seconds": sum(r["seconds"] for r in rs) / n,
        }
        if lv in ("D", "E"):
            s["first_attempt_pass"] = sum(r["first_pass"] for r in rs) / n
            s["fallback"] = sum(r["fallback"] for r in rs) / n
            s["first_attempt_invented_numbers"] = sum(r["first_attempt_audit"]["invented_numbers"] > 0 for r in rs) / n
        if lv == "E":
            s["replay_tools_match"] = sum(r["replay_tools_match"] for r in rs) / n
            s["replay_llm_match"] = sum(bool(r["replay_llm_match"]) for r in rs) / n
            s["audit_trail_complete"] = sum(all(r["audit_trail"].values()) for r in rs) / n
        out[lv] = s
    return out


ROWS = [
    ("Uydurma sayı (soru başına)", "invented_numbers"),
    ("Uydurma tarih", "invented_dates"),
    ("Yasaklı ifade", "forbidden_phrases"),
    ("Kapının izin vermediği eylem", "action_not_allowed_by_gate"),
    ("Backtest'siz aday etiketi", "candidate_without_backtest"),
    ("Tavsiye sorusunda ret yok", "refusal_missing"),
    ("Kanıtsız sonuç", "unsupported_conclusion"),
    ("Bozuk/geçersiz cevap (JSON)", "invalid_answer"),
    ("Herhangi bir kural ihlali", "any_rule_violation"),
    ("Araç çağrısı / soru", "tool_calls_per_question"),
    ("Hatalı araç çağrısı oranı", "invalid_call_rate"),
    ("as_of ihlali (adet)", "as_of_violations"),
    ("Çalışan ileri tarih çağrısı (adet)", "lookahead_calls_executed"),
    ("Veri kalitesi atlandı", "quality_check_skipped"),
    ("Backtest atlandı", "backtest_skipped"),
    ("Risk kapısı atlandı", "risk_gate_skipped"),
    ("İlk denemede geçti", "first_attempt_pass"),
    ("Güvenli şablona düştü", "fallback"),
    ("Tekrar: araç hash'leri aynı", "replay_tools_match"),
    ("Tekrar: LLM çıktısı aynı", "replay_llm_match"),
    ("İz kaydı tam", "audit_trail_complete"),
    ("Süre (sn/soru)", "mean_seconds"),
]
COUNTS = {"as_of_violations", "lookahead_calls_executed"}
RAW = {"tool_calls_per_question", "mean_seconds"}


def print_table(model: str, summ: dict[str, dict[str, Any]]) -> None:
    lv = [x for x in LEVELS if x in summ]
    print(f"\n{model}  (n={summ[lv[0]]['n']} soru)")
    print(f"{'':36s}" + "".join(f"{x:>8s}" for x in lv))
    for label, key in ROWS:
        cells = []
        for x in lv:
            v = summ[x].get(key)
            if v is None:
                cells.append("-")
            elif key in COUNTS:
                cells.append(str(v))
            elif key in RAW:
                cells.append(f"{v:.1f}")
            else:
                cells.append(f"{v:.0%}")
        if any(c != "-" for c in cells):
            print(f"{label:36s}" + "".join(f"{c:>8s}" for c in cells))


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eval.ablation")
    p.add_argument("--models", default="bist-analist,qwen3.5:4b")
    p.add_argument("--only", default="", help="comma-separated question ids")
    p.add_argument("--out", default=str(project_root() / "reports" / "ablation"))
    p.add_argument("--resume", action="store_true", help="keep finished questions of an interrupted run")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    only = {x for x in a.only.split(",") if x}
    qs = [(q, r) for q, r in questions(["golden", "heldout"]) if not only or q in only]
    ctx, policy = tool_context(), load_policy()
    print(f"{len(qs)} questions x levels {','.join(LEVELS)}", flush=True)
    for model in [m for m in a.models.split(",") if m]:
        safe = model.replace(":", "_").replace("/", "_")
        db = out / f"episodic_{safe}.sqlite"
        partial = out / f"ablation_{safe}.partial.jsonl"  # one line per finished question (survives a crash)
        rows: list[dict[str, Any]] = []
        if a.resume and partial.exists():
            for line in partial.read_text(encoding="utf-8").splitlines():
                rows += json.loads(line)
            print(f"  {model}: resuming, {len({r['id'] for r in rows})} questions already done", flush=True)
        else:  # this script's own audit DB and progress file: one fresh trail per run
            db.unlink(missing_ok=True)
            partial.unlink(missing_ok=True)
        mem = EpisodicMemory(db)
        done = {r["id"] for r in rows}
        for qid, req in qs:
            if qid in done:
                continue
            t0 = time.perf_counter()
            new = run_question(qid, req, model, ctx, policy, mem)
            rows += new
            with partial.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(new, ensure_ascii=False) + "\n")
            line = " ".join(
                f"{r['level']}:{'IHLAL' if r['audit']['rule_violation'] else 'ok'}"
                f"{'/uydurma' if r['audit']['invented_numbers'] else ''}"
                for r in new
            )
            e = new[-1]
            print(
                f"  {model:13s} {qid:4s} {line}  replay={'OK' if e['replay_tools_match'] and e['replay_llm_match'] else 'FARK'} "
                f"{time.perf_counter() - t0:.0f}s",
                flush=True,
            )
        summ = summarise(rows)
        (out / f"ablation_{safe}.json").write_text(
            json.dumps({"model": model, "summary": summ, "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print_table(model, summ)
    return 0


if __name__ == "__main__":
    sys.exit(main())
