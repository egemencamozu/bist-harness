"""Golden suite: the instructor's five questions end to end through the harness, checked against `expected`.

uv run python -m eval.run_golden [--explainer template|llm] [--model qwen2.5:7b] [--only Q1,Q3] [--out reports/golden.json]

Checks per question (deterministic, from tool outputs, never from LLM prose): mandatory states ran; no invalid tool
call; the explanation passed the validator (or the safe fallback was used); the action is allowed by the gate and by
`expected.allowed_actions`; required evidence keys were committed; expected incomplete windows / invisible reports
are reported; advice requests carry the refusal. Exit code 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from datetime import date
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from bistharness.core.config import project_root
from bistharness.core.enums import ALLOWED_ACTIONS_BY_GATE, Scenario, StateStatus
from bistharness.harness.factory import build_config, tool_context
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.policy import load_policy
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.runner import AnalysisResult, run_analysis

GOLDEN = project_root() / "eval" / "golden_questions.json"


def load_golden() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def request_of(q: dict[str, Any], as_of: date) -> AnalysisRequest:
    return AnalysisRequest(
        question=q["question"],
        scenario=Scenario(q["scenario"]),
        tickers=q["tickers"],
        as_of_date=as_of,
        params=q.get("params", {}),
        advice_requested=bool(q.get("advice_requested", False)),
    )


def check(q: dict[str, Any], res: AnalysisResult) -> dict[str, bool]:
    exp = q.get("expected", {})
    e = res.explanation
    committed = [c["key"] for c in res.bundle.get("committed", [])]
    st = {s.state: s.status for s in res.states}
    out: dict[str, bool] = {
        "mandatory_states_done": all(
            st[s] is StateStatus.DONE for s in st if s.value in ("CHECK_DATA_QUALITY", "RUN_BACKTEST", "RISK_GATE")
        ),
        "no_invalid_tool_calls": not res.invalid_calls,
        "explanation_validated": e is not None and (e.fallback_used or e.attempts[-1].validation.ok),
        "action_allowed_by_gate": e is not None and e.action in ALLOWED_ACTIONS_BY_GATE[res.gate],
    }
    if "allowed_actions" in exp and e is not None:
        out["action_in_expected_set"] = e.action.value in exp["allowed_actions"]
    for pat in exp.get("required_evidence", []):
        out[f"evidence:{pat}"] = any(fnmatchcase(k, pat) for k in committed)
    if exp.get("refusal"):
        out["refusal_present"] = e is not None and e.text_tr.startswith(res_policy_refusal(res))
    excluded = [x for c in res.calls if c.envelope is not None for x in c.envelope.excluded_incomplete_events]
    for item in exp.get("excluded_incomplete", []):
        out[f"excluded:{item['ticker']}:{item['event_date']}:h{item['horizon']}"] = any(
            x.ticker == item["ticker"]
            and x.event_date.isoformat() == item["event_date"]
            and x.horizon == item["horizon"]
            and x.trading_days_available == item["trading_days_available"]
            for x in excluded
        )
    if exp.get("must_report_excluded_incomplete"):
        out["excluded_reported"] = bool(excluded) and any("excluded" in k for k in committed)
    for item in exp.get("not_visible_reports", []):
        env = next(
            (
                c.envelope
                for c in res.calls
                if c.envelope is not None
                and c.tool == "calculate_fundamental_change"
                and c.envelope.inputs.get("ticker") == item["ticker"]
            ),
            None,
        )
        periods = [r["fiscal_period"] for r in env.result.get("reports", [])] if env else []
        out[f"invisible:{item['ticker']}:{item['fiscal_period']}"] = (
            env is not None and item["fiscal_period"] not in periods
        )
    lr = exp.get("latest_report")
    if lr:
        env = res.envelope("calculate_fundamental_change")
        last = env.result["reports"][-1] if env and env.result.get("reports") else {}
        out["latest_report"] = (
            last.get("fiscal_period") == lr["fiscal_period"]
            and last.get("disclosure_datetime") == lr["disclosure_datetime"]
            and (not lr.get("window_20d_complete") or "20" in last.get("reaction", {}))
        )
    return out


def res_policy_refusal(res: AnalysisResult) -> str:
    return load_policy().validation.refusal_template


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eval.run_golden")
    p.add_argument("--explainer", choices=["template", "llm"], default="template")
    p.add_argument("--model", default=None)
    p.add_argument("--only", default="")
    p.add_argument("--out", default="")
    args = p.parse_args(argv)
    g = load_golden()
    as_of = date.fromisoformat(g["as_of_date"])
    ctx = tool_context()
    mem = EpisodicMemory(":memory:") if not args.out else None
    cfg = build_config(explainer=args.explainer, model=args.model, memory=mem)
    only = {x for x in args.only.split(",") if x}
    rows, failed = [], 0
    for q in g["questions"]:
        if only and q["id"] not in only:
            continue
        t0 = time.perf_counter()
        res = run_analysis(request_of(q, as_of), ctx, cfg)
        checks = check(q, res)
        ok = all(checks.values())
        failed += 0 if ok else 1
        e = res.explanation
        rows.append(
            {
                "id": q["id"],
                "ok": ok,
                "seconds": round(time.perf_counter() - t0, 1),
                "gate": res.gate.value,
                "action": e.action.value if e else None,
                "teacher_action": e.teacher_action.value if e and e.teacher_action else None,
                "attempts": len(e.attempts) if e else 0,
                "fallback": e.fallback_used if e else None,
                "checks": checks,
                "decision_id": res.decision_id,
                "text": e.text_tr if e else "",
            }
        )
        bad = [k for k, v in checks.items() if not v]
        print(
            f"{q['id']} {'PASS' if ok else 'FAIL'} {rows[-1]['seconds']:6.1f}s gate={res.gate.value:18s} "
            f"action={rows[-1]['action']:34s} teacher={rows[-1]['teacher_action']} attempts={rows[-1]['attempts']}"
            + (f"  failed: {bad}" if bad else "")
        )
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps({"explainer": args.explainer, "model": args.model, "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"\n{len(rows) - failed}/{len(rows)} golden questions passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
