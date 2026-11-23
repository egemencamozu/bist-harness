"""Harness CLI.

uv run python -m bistharness.harness run --as-of 2026-09-10 --question "ASELS'te alt Bollinger dokunuşları ..." \
    [--scenario S3_TECHNICAL_REVERSAL --tickers ASELS] [--explainer template|llm] [--planner scenario|llm]
    [--intent rules|llm|hybrid] [--model bist-analist]
uv run python -m bistharness.harness replay --decision D-... [--llm]
uv run python -m bistharness.harness review --decision D-... --verdict ACCEPT --reason "..."
uv run python -m bistharness.harness list
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from bistharness.core.enums import ReviewVerdict, Scenario
from bistharness.harness.factory import build_config, default_memory_path, ollama_client
from bistharness.harness.intent import UNDERSTAND_MODES, understand_question
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.policy import load_policy
from bistharness.harness.replay import replay_analysis
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.runner import run_analysis
from bistharness.tools import ToolContext


def _run(args: argparse.Namespace) -> int:
    ctx = ToolContext.from_settings()
    as_of = date.fromisoformat(args.as_of)
    if args.scenario:
        req = AnalysisRequest(
            question=args.question, scenario=Scenario(args.scenario), tickers=args.tickers.split(","), as_of_date=as_of
        )
    else:
        client = ollama_client(load_policy(), args.model) if args.intent != "rules" else None
        u = understand_question(args.question, as_of=as_of, universe=ctx.universe, client=client, mode=args.intent)
        if u.request is None:
            print(f"Soru analiz edilmedi ({u.method}): {u.message_tr}")
            return 2
        req = u.request
        print(
            f"understood by {u.method}: {req.scenario.value} {list(req.tickers)} params={req.params}"
            + (" [advice override]" if u.advice_override else "")
        )
    cfg = build_config(explainer=args.explainer, planner=args.planner, model=args.model)
    res = run_analysis(req, ctx, cfg)
    print(
        f"analysis {res.analysis_id}  decision {res.decision_id}  scenario {req.scenario.value}  gate {res.gate.value}"
    )
    for s in res.states:
        print(f"  {s.state.value:36s} {s.status.value:24s} calls={len(s.calls)} {s.reason or ''}")
    for c in res.invalid_calls:
        print(f"  INVALID {c.state.value} {c.tool}: {c.error}")
    print("\nCommitted evidence:")
    for c in res.bundle.get("committed", []):
        print(f"  {c['id']}: {c['claim_tr']}")
    if res.explanation:
        print(f"\nACTION: {res.explanation.action.value}  (fallback={res.explanation.fallback_used})\n")
        print(res.explanation.text_tr)
    return 0


def _replay(args: argparse.Namespace) -> int:
    ctx = ToolContext.from_settings()
    mem = EpisodicMemory(default_memory_path())
    client = ollama_client(load_policy()) if args.llm else None
    rep = replay_analysis(args.decision, ctx, mem, client)
    print(f"decision {rep.decision_id}  data_version_match={rep.data_version_match}  tools_match={rep.tools_match}")
    for c in rep.calls:
        print(f"  {c.seq:3d} {c.state:32s} {c.tool:30s} {c.basis:12s} {'OK' if c.match else 'DIFF'}")
    if rep.llm_compared:
        print(f"  LLM output identical: {rep.llm_match}  {rep.llm_diff or ''}")
    return 0 if rep.tools_match and rep.llm_match is not False else 1


def _review(args: argparse.Namespace) -> int:
    mem = EpisodicMemory(default_memory_path())
    if mem.decision(args.decision) is None:
        print(f"unknown decision {args.decision}")
        return 1
    mem.add_review(
        args.decision,
        reviewer=args.reviewer,
        verdict=ReviewVerdict(args.verdict).value,
        reason=args.reason,
        modified_action=args.action,
    )
    print("review stored")
    return 0


def _list(args: argparse.Namespace) -> int:
    mem = EpisodicMemory(default_memory_path())
    for a in mem.analyses(args.limit):
        print(
            f"{a['created_at']}  {a['analysis_id']}  {a['scenario']:24s} {a['as_of_date']}  {a['gate'] or '-':18s} "
            f"{a['action'] or '-':34s} {a['explainer']}"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bistharness.harness")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--question", required=True)
    r.add_argument("--as-of", required=True)
    r.add_argument("--scenario", choices=[s.value for s in Scenario])
    r.add_argument("--tickers", default="")
    r.add_argument("--explainer", choices=["template", "llm"], default="template")
    r.add_argument("--planner", choices=["scenario", "llm"], default="scenario")
    r.add_argument("--model", default=None)
    r.add_argument(
        "--intent", choices=UNDERSTAND_MODES, default="hybrid", help="free-text understanding: rules / llm / hybrid"
    )
    r.set_defaults(fn=_run)
    rp = sub.add_parser("replay")
    rp.add_argument("--decision", required=True)
    rp.add_argument("--llm", action="store_true")
    rp.set_defaults(fn=_replay)
    rv = sub.add_parser("review")
    rv.add_argument("--decision", required=True)
    rv.add_argument("--verdict", choices=["ACCEPT", "MODIFY", "REJECT"], required=True)
    rv.add_argument("--reason", required=True)
    rv.add_argument("--action", default=None)
    rv.add_argument("--reviewer", default="human")
    rv.set_defaults(fn=_review)
    ls = sub.add_parser("list")
    ls.add_argument("--limit", type=int, default=20)
    ls.set_defaults(fn=_list)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
