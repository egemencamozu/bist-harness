"""Fine-tuning dataset from REAL tool outputs (CLAUDE.md §9; no cloud LLM, no synthetic market data).

uv run python -m training.generate_dataset --n-explain 2500 --n-intent 1500 --n-plan 1000 --workers 8 --out training/data

Three skills, all in chat format (system / user / assistant JSON), exactly the prompts the harness sends at inference:
- intent:      question -> structured request (harness/intent.py); includes out-of-scope and advice questions
- planning:    state + request -> tool_calls of the deterministic ScenarioPlanner (harness/planner.py)
- explanation: committed evidence (E1..En) + gate -> validated teacher JSON (TemplateExplainer, phrasing variants)
Every explanation target passes the validator; a job whose teacher falls back is dropped and counted.

Leakage guard (eval/splits.json): no as_of within `min_gap_trading_days` of the golden date or a held-out date; the
validation split uses its own as_of dates (disjoint from the training dates).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from bistharness.core.config import load_universe, project_root
from bistharness.core.enums import Scenario
from bistharness.harness.explainer import SYSTEM_PROMPT, TemplateExplainer, user_prompt
from bistharness.harness.intent import intent_messages
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.planner import ScenarioPlanner, planner_messages
from bistharness.harness.policy import load_policy
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.runner import ANALYSIS_STATES, HarnessConfig, run_analysis
from training.question_bank import company_names, make_question, out_of_scope

SCENARIO_WEIGHTS = {
    Scenario.S1_SECTOR_CATCH_UP: 0.22,
    Scenario.S2_WEEKDAY_PATTERN: 0.16,
    Scenario.S3_TECHNICAL_REVERSAL: 0.22,
    Scenario.S4_FUNDAMENTAL_REACTION: 0.22,
    Scenario.SAFETY_ADVICE_REQUEST: 0.18,
}
PATTERNS = ("MON_TUE_WED_DOWN__THU_FRI", "MON_DOWN__FRI", "MON_TO_THU_UP__FRI", "THREE_DOWN_DAYS", "LARGE_DOWN_DAY")
ANALYSIS_START = date(2024, 1, 1)


@dataclass
class Job:
    id: str
    split: str
    scenario: str
    tickers: list[str]
    as_of: str
    question: str
    params: dict[str, Any] = field(default_factory=dict)
    variant: int = 0
    plan: bool = False


# ----------------------------------------------------------------------------------------------- dates
def eligible_dates(seed: int) -> tuple[list[date], list[date]]:
    from bistharness.harness.factory import tool_context

    splits = json.loads((project_root() / "eval" / "splits.json").read_text(encoding="utf-8"))
    cal = tool_context().repo.trading_calendar(as_of="2026-11-19")
    days = [d for d in cal.days if d >= date(2024, 7, 1)]
    reserved = [date.fromisoformat(splits["golden_as_of"]), *(date.fromisoformat(x) for x in splits["heldout_as_of"])]
    gap = int(splits["min_gap_trading_days"])
    pos = {d: i for i, d in enumerate(days)}
    blocked: set[int] = set()
    for r in reserved:
        i = min(range(len(days)), key=lambda k: abs((days[k] - r).days))
        blocked |= set(range(max(0, i - gap), min(len(days), i + gap + 1)))
    ok = [d for d in days if pos[d] not in blocked]
    picked = ok[::12]  # ~every 12 trading days -> varied market states without near-duplicate evidence
    rng = random.Random(seed)
    val = sorted(rng.sample(picked, max(3, len(picked) // 8)))
    train = [d for d in picked if d not in val]
    return train, val


# ----------------------------------------------------------------------------------------------- jobs
def make_jobs(n: int, seed: int, train_dates: list[date], val_dates: list[date], plan_share: float) -> list[Job]:
    rng = random.Random(seed)
    u = load_universe()
    names = company_names()
    stocks = list(u.all_stock_tickers())
    groups = [g for g, m in u.peer_groups.items() if len(m) >= 2]
    scen = list(SCENARIO_WEIGHTS)
    weights = [SCENARIO_WEIGHTS[s] for s in scen]
    jobs: list[Job] = []
    for i in range(n):
        split = "val" if rng.random() < 0.1 else "train"
        sc = rng.choices(scen, weights)[0]
        params: dict[str, Any] = {}
        pool = val_dates if split == "val" else train_dates
        if sc is Scenario.S2_WEEKDAY_PATTERN:
            pool = [d for d in pool if d >= date(2025, 3, 1)] or pool
        as_of = rng.choice(pool)
        if sc is Scenario.S1_SECTOR_CATCH_UP:
            members = list(u.peer_groups[rng.choice(groups)])
            k = rng.randint(2, min(5, len(members)))
            tickers = sorted(rng.sample(members, k)) if rng.random() < 0.6 else [rng.choice(members)]
            if len(tickers) == 1 and len(u.peers(tickers[0])) < 2:
                tickers = members[:2]
            params["horizon"] = rng.choice([10, 20, 20, 20, 60])
        else:
            tickers = [rng.choice(stocks)]
        if sc is Scenario.S2_WEEKDAY_PATTERN:
            oos_start = as_of - timedelta(days=rng.choice([120, 180, 240]))
            params.update(
                {
                    "pattern": rng.choice(PATTERNS),
                    "in_sample_start": ANALYSIS_START.isoformat(),
                    "in_sample_end": (oos_start - timedelta(days=1)).isoformat(),
                    "out_of_sample_start": oos_start.isoformat(),
                    "tx_cost_bps": rng.choice([5, 10, 10, 20]),
                }
            )
        q = make_question(sc, tickers, rng, names, u, params)
        jobs.append(
            Job(
                f"J{i:05d}",
                split,
                sc.value,
                tickers,
                as_of.isoformat(),
                q.text,
                params,
                rng.randrange(1000),
                rng.random() < plan_share,
            )
        )
    return jobs


# ----------------------------------------------------------------------------------------------- worker
_CTX: Any = None
_POLICY: Any = None


def _init() -> None:
    global _CTX, _POLICY
    from bistharness.harness.factory import tool_context

    _CTX = tool_context()
    _POLICY = load_policy()


def _json(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(", ", ": "))


def run_job(job: Job) -> dict[str, Any]:
    t0 = time.perf_counter()
    req = AnalysisRequest(
        question=job.question,
        scenario=Scenario(job.scenario),
        tickers=job.tickers,
        as_of_date=date.fromisoformat(job.as_of),
        start=ANALYSIS_START,
        params=job.params,
        advice_requested=job.scenario == Scenario.SAFETY_ADVICE_REQUEST.value,
    )
    teacher = TemplateExplainer(_POLICY, variant=job.variant)
    try:
        res = run_analysis(req, _CTX, HarnessConfig(ScenarioPlanner(_POLICY), teacher, EpisodicMemory()))
    except Exception as exc:  # recorded, never silently dropped
        return {"job": asdict(job), "error": f"{type(exc).__name__}: {exc}"[:400], "examples": []}
    out: list[dict[str, Any]] = []
    e = res.explanation
    meta = {"job": job.id, "split": job.split, "scenario": job.scenario, "tickers": job.tickers, "as_of": job.as_of}
    ok = e is not None and not e.fallback_used
    if ok and e is not None:
        target = json.loads(e.attempts[0].raw)
        out.append(
            {
                "skill": "explanation",
                **meta,
                "gate": res.gate.value,
                "action": e.action.value,
                "rule": e.teacher_rule,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt(req, res.bundle, res.gate)},
                    {"role": "assistant", "content": _json(target)},
                ],
            }
        )
    intent = {
        "in_scope": True,
        "scenario": job.scenario,
        "tickers": job.tickers,
        "advice_requested": req.advice_requested,
        "params": job.params,
        "reason_tr": "",
    }
    out.append(
        {
            "skill": "intent",
            **meta,
            "messages": [
                *intent_messages(job.question, req.as_of_date),
                {"role": "assistant", "content": _json(intent)},
            ],
        }
    )
    if job.plan:
        done: list[dict[str, Any]] = []
        for st in res.states:
            calls = [c for c in st.calls if c.origin == "plan" and c.valid]
            if st.state in ANALYSIS_STATES and calls:
                allowed = sorted(_POLICY.permissions[st.state])
                target = {"tool_calls": [{"tool": c.tool, "arguments": c.arguments} for c in calls]}
                out.append(
                    {
                        "skill": "planning",
                        **meta,
                        "state": st.state.value,
                        "messages": [
                            *planner_messages(st.state, req, done, allowed),
                            {"role": "assistant", "content": _json(target)},
                        ],
                    }
                )
            done += [{"tool": c.tool, "arguments": c.arguments} for c in st.calls if c.valid]
    return {
        "job": asdict(job),
        "error": None if ok else "teacher_fallback",
        "seconds": time.perf_counter() - t0,
        "examples": out,
    }


# ----------------------------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="training.generate_dataset")
    p.add_argument("--n-explain", type=int, default=2500)
    p.add_argument("--n-intent-extra", type=int, default=300, help="out-of-scope / advice intent questions")
    p.add_argument("--plan-share", type=float, default=0.15, help="share of jobs that also yield planning examples")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default=str(project_root() / "training" / "data"))
    p.add_argument("--limit", type=int, default=0, help="debug: only the first N jobs")
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    train_dates, val_dates = eligible_dates(args.seed)
    jobs = make_jobs(args.n_explain, args.seed, train_dates, val_dates, args.plan_share)
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"{len(jobs)} jobs; train dates {len(train_dates)} val dates {len(val_dates)}", flush=True)
    shard = out / "shard_examples.jsonl"
    done_ids: set[str] = set()
    if shard.exists():  # resume
        for line in shard.read_text(encoding="utf-8").splitlines():
            done_ids.add(json.loads(line)["job"]["id"])
    todo = [j for j in jobs if j.id not in done_ids]
    t0 = time.perf_counter()
    with (
        ProcessPoolExecutor(max_workers=args.workers, initializer=_init) as pool,
        shard.open("a", encoding="utf-8") as fh,
    ):
        futs = [pool.submit(run_job, j) for j in todo]
        for k, f in enumerate(as_completed(futs), 1):
            fh.write(json.dumps(f.result(), ensure_ascii=False) + "\n")
            fh.flush()
            if k % 50 == 0 or k == len(futs):
                el = time.perf_counter() - t0
                print(
                    f"  {k}/{len(futs)} jobs  {el / 60:.1f} min  eta {(len(futs) - k) * el / k / 60:.1f} min",
                    flush=True,
                )
    # extra intent questions: out of scope and pure advice
    rng = random.Random(args.seed + 1)
    extra = []
    for i in range(args.n_intent_extra):
        q = out_of_scope(rng)
        as_of = rng.choice(train_dates)
        target = {
            "in_scope": False,
            "scenario": None,
            "tickers": [],
            "advice_requested": q.advice,
            "params": {},
            "reason_tr": q.reason,
        }
        extra.append(
            {
                "skill": "intent",
                "job": f"X{i:05d}",
                "split": "val" if i % 10 == 0 else "train",
                "scenario": None,
                "tickers": [],
                "as_of": as_of.isoformat(),
                "messages": [*intent_messages(q.text, as_of), {"role": "assistant", "content": _json(target)}],
            }
        )
    # merge, dedupe, split
    rows = [json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines()]
    errors = Counter(r["error"] for r in rows if r["error"])
    examples = [ex for r in rows for ex in r["examples"]] + extra
    seen, final = set(), []
    for ex in examples:
        h = hashlib.sha256(json.dumps(ex["messages"], ensure_ascii=False).encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            final.append(ex)
    for split in ("train", "val"):
        part = [ex for ex in final if ex["split"] == split]
        (out / f"{split}.jsonl").write_text(
            "\n".join(json.dumps(ex, ensure_ascii=False) for ex in part) + "\n", encoding="utf-8"
        )
    stats = {
        "jobs": len(rows),
        "job_errors": dict(errors),
        "examples": len(final),
        "by_split_skill": dict(Counter(f"{ex['split']}/{ex['skill']}" for ex in final)),
        "explanation_by_scenario": dict(Counter(ex["scenario"] for ex in final if ex["skill"] == "explanation")),
        "explanation_by_action": dict(Counter(ex["action"] for ex in final if ex["skill"] == "explanation")),
        "explanation_by_gate": dict(Counter(ex["gate"] for ex in final if ex["skill"] == "explanation")),
        "train_dates": [d.isoformat() for d in train_dates],
        "val_dates": [d.isoformat() for d in val_dates],
        "distinct_tickers": len({t for ex in final for t in ex.get("tickers", [])}),
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
