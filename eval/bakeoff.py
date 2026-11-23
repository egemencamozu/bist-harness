"""Base-model bake-off: which local model explains our evidence best (before any fine-tuning)?

uv run python -m eval.bakeoff --models qwen2.5:7b,qwen3.5:9b,qwen3.5:4b [--set golden,heldout] [--out reports/bakeoff]

The tools/harness run ONCE per question (template explainer) and the identical evidence bundle is given to every
model, so the comparison isolates the explanation skill. Metrics (all programmatic): first-attempt validator pass,
final pass without the safe fallback, invented numbers / forbidden phrases in the first attempt, agreement with the
deterministic decision policy (teacher), seconds per question.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from bistharness.core.config import project_root
from bistharness.core.enums import GateStatus, Scenario
from bistharness.harness.explainer import LLMExplainer
from bistharness.harness.factory import build_config, ollama_client, tool_context
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.policy import load_policy
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.runner import run_analysis

EVAL = project_root() / "eval"


def questions(sets: Sequence[str]) -> list[tuple[str, AnalysisRequest]]:
    out: list[tuple[str, AnalysisRequest]] = []
    if "golden" in sets:
        g = json.loads((EVAL / "golden_questions.json").read_text(encoding="utf-8"))
        for q in g["questions"]:
            out.append(
                (
                    q["id"],
                    AnalysisRequest(
                        question=q["question"],
                        scenario=Scenario(q["scenario"]),
                        tickers=q["tickers"],
                        as_of_date=date.fromisoformat(g["as_of_date"]),
                        params=q.get("params", {}),
                        advice_requested=bool(q.get("advice_requested", False)),
                    ),
                )
            )
    if "heldout" in sets:
        h = json.loads((EVAL / "heldout_questions.json").read_text(encoding="utf-8"))
        for q in h["questions"]:
            out.append(
                (
                    q["id"],
                    AnalysisRequest(
                        question=q["question"],
                        scenario=Scenario(q["scenario"]),
                        tickers=q["tickers"],
                        as_of_date=date.fromisoformat(q["as_of"]),
                        params=q.get("params", {}),
                        advice_requested=bool(q.get("advice_requested", False)),
                    ),
                )
            )
    return out


def bundles(qs: list[tuple[str, AnalysisRequest]], cache: Path) -> dict[str, dict[str, Any]]:
    """qid -> {request, bundle, gate, teacher_action}; computed once and cached."""
    have: dict[str, dict[str, Any]] = {}
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            have[row["id"]] = row
    ctx = tool_context()
    cfg = build_config(explainer="template", memory=EpisodicMemory())
    for qid, req in qs:
        if qid in have and have[qid]["request"] == req.model_dump(mode="json"):
            continue
        res = run_analysis(req, ctx, cfg)
        e = res.explanation
        have[qid] = {
            "id": qid,
            "request": req.model_dump(mode="json"),
            "bundle": res.bundle,
            "gate": res.gate.value,
            "teacher_action": e.teacher_action.value if e and e.teacher_action else None,
            "invalid_calls": len(res.invalid_calls),
        }
        print(
            f"  bundle {qid}: gate={res.gate.value} committed={len(res.bundle.get('committed', []))} "
            f"invalid={len(res.invalid_calls)}",
            flush=True,
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("\n".join(json.dumps(v, ensure_ascii=False) for v in have.values()), encoding="utf-8")
    return have


def run_model(
    model: str, qs: list[tuple[str, AnalysisRequest]], data: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    policy = load_policy()
    explainer = LLMExplainer(ollama_client(policy, model), policy)
    rows = []
    for qid, req in qs:
        d = data[qid]
        t0 = time.perf_counter()
        e = explainer.explain(req, d["bundle"], GateStatus(d["gate"]))
        first = e.attempts[0].validation
        rows.append(
            {
                "id": qid,
                "model": model,
                "scenario": req.scenario.value,
                "seconds": round(time.perf_counter() - t0, 1),
                "first_pass": first.ok,
                "final_ok": not e.fallback_used,
                "attempts": len(e.attempts),
                "invented_numbers": len(first.bad_numbers),
                "forbidden_hits": len(first.forbidden_hits),
                "first_errors": first.errors,
                "first_raw": e.attempts[0].raw,
                "action": e.action.value,
                "teacher_action": d["teacher_action"],
                "agrees_with_teacher": e.action.value == d["teacher_action"],
                "text": e.text_tr,
            }
        )
        r = rows[-1]
        print(
            f"  {model:14s} {qid:4s} first={'OK' if r['first_pass'] else 'X'} final={'OK' if r['final_ok'] else 'FALLBACK'} "
            f"action={r['action']:34s} teacher={r['teacher_action']} {r['seconds']}s",
            flush=True,
        )
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {
        "n": n,
        "first_attempt_pass": sum(r["first_pass"] for r in rows) / n,
        "final_without_fallback": sum(r["final_ok"] for r in rows) / n,
        "questions_with_invented_numbers": sum(r["invented_numbers"] > 0 for r in rows) / n,
        "questions_with_forbidden_phrases": sum(r["forbidden_hits"] > 0 for r in rows) / n,
        "teacher_agreement": sum(r["agrees_with_teacher"] for r in rows) / n,
        "mean_seconds": sum(r["seconds"] for r in rows) / n,
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eval.bakeoff")
    p.add_argument("--models", default="qwen2.5:7b,qwen3.5:9b,qwen3.5:4b")
    p.add_argument("--set", default="golden,heldout")
    p.add_argument("--out", default=str(project_root() / "reports" / "bakeoff"))
    args = p.parse_args(argv)
    out = Path(args.out)
    qs = questions(args.set.split(","))
    print(f"{len(qs)} questions; computing evidence bundles (cached) ...", flush=True)
    data = bundles(qs, out / "bundles.jsonl")
    out.mkdir(parents=True, exist_ok=True)
    for model in [m for m in args.models.split(",") if m]:
        rows = run_model(model, qs, data)
        safe = model.replace(":", "_").replace("/", "_")
        (out / f"results_{safe}.json").write_text(
            json.dumps({"model": model, "summary": summary(rows), "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    # combined table over every model evaluated so far (each model's file is kept)
    results = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(out.glob("results_*.json"))]
    if results:
        print()
        print("model           first_pass  no_fallback  invented  forbidden  teacher_agree  sec/q")
        for r in results:
            s_ = r["summary"]
            print(
                f"{r['model']:15s} {s_['first_attempt_pass']:10.0%} {s_['final_without_fallback']:12.0%} "
                f"{s_['questions_with_invented_numbers']:9.0%} {s_['questions_with_forbidden_phrases']:10.0%} "
                f"{s_['teacher_agreement']:14.0%} {s_['mean_seconds']:6.1f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
