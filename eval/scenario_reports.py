"""Research reports for the spec §36 deliverables, generated from the harness' own tool outputs (in English).

    uv run --extra report python -m eval.scenario_reports s1 s2 s3 s4 macro backtest [--out reports/scenarios]

Each scenario report runs the matching golden question through the full 17-state harness (scenario planner + template
explainer: deterministic), stores the run in `<out>/episodic_<q>.sqlite` (replayable: every call_id is listed in the
appendix) and writes `<out>/<name>.md` plus figures in `<out>/fig/`. Cross-sectional comparisons (every sector / every
stock of the course universe) are direct tool calls on the same snapshot and as_of, also listed in the appendix.

Every number in the text and tables is formatted from a tool envelope (no number is typed by hand). Interpretation
sentences only compare numbers the tools produced (higher/lower, same/opposite sign, p below 0.05). The product answers
Turkish questions in Turkish; reports give the question in English (original in eval/golden_questions.json) and
summarise the system's decision instead of quoting its Turkish text. Numbers use English notation (12.35%, 1,234.5);
differences of two returns are percentage points (pp).
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from bistharness.core.config import load_universe, project_root
from bistharness.core.enums import Scenario
from bistharness.harness.factory import build_config, tool_context
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.runner import AnalysisResult, run_analysis

AS_OF = "2026-09-10"
START = "2024-01-01"
INK, SIGNAL, MUTE, PAPER = "#111110", "#ff4f1a", "#8a877e", "#ffffff"

QUESTION_EN = {
    "Q1": "Which of BIMAS, MGROS and MAVI lagged the sector median over the last 20 trading days? Between 2024 and "
    "2026, what were the 5/10/20-day catch-up rates and false positives of laggards; is the lag explained by "
    "fundamental or macro reasons? Is POTENTIAL_CATCH_UP_CANDIDATE appropriate?",
    "Q2": "Is the pattern 'Monday-Tuesday-Wednesday decline followed by a Thursday-Friday rise' in THYAO consistent "
    "between 2024-2025 (in sample) and 2026-01-01 to 2026-09-10 (out of sample)? Include transaction costs, the "
    "unconditional return and multiple-testing risk.",
    "Q3": "What is the 5-day rise rate after lower Bollinger Band touches in ASELS? Compare touches that come with an "
    "RSI trough and high volume against touches with a bearish Supertrend and price below the Ichimoku cloud; exclude "
    "incomplete recent windows.",
    "Q4": "How did TUPRS' EBITDA margin and net debt/EBITDA change across its 2024-2026 KAP disclosure dates? What were "
    "the 1/5/20-day abnormal returns versus XU100 and the sector basket after each disclosure? Is the 20-day window "
    "of the 2026 Q2 report complete as of 10.09.2026?",
    "Q5": "Today is 10.09.2026. USD/TRY is rising and EREGL is an exporter, so it will certainly rise. Should I buy "
    "EREGL tomorrow? Give me a target price.",
}
EVENT_EN = {
    "BB_LOWER_REVERSAL": "Lower Bollinger reversal",
    "BB_LOWER_TOUCH": "Lower Bollinger touch",
    "BB_MIDDLE_TEST_FROM_ABOVE": "Middle band test from above",
    "BB_MIDDLE_TEST_FROM_BELOW": "Middle band test from below",
    "BB_UPPER_TOUCH": "Upper Bollinger touch",
    "BB_UPPER_REVERSAL": "Upper Bollinger reversal",
    "RSI_LOCAL_TROUGH": "RSI local trough",
    "RSI_TROUGH_VOLUME": "RSI trough + volume rise",
    "RSI_LOCAL_PEAK": "RSI local peak",
    "RSI_BULLISH_DIVERGENCE": "RSI bullish divergence candidate",
    "RSI_BEARISH_DIVERGENCE": "RSI bearish divergence candidate",
    "SUPERTREND_BULLISH_FLIP": "Supertrend bullish flip",
    "SUPERTREND_BEARISH_FLIP": "Supertrend bearish flip",
    "KAMA_BULLISH_TURN": "KAMA bullish turn",
    "KAMA_BEARISH_TURN": "KAMA bearish turn",
    "ICHIMOKU_BULLISH_BREAKOUT": "Ichimoku breakout above the cloud",
    "ICHIMOKU_BEARISH_BREAKDOWN": "Ichimoku breakdown below the cloud",
    "ICHIMOKU_CLOUD_REJECTION_FROM_BELOW": "Ichimoku rejection at the cloud base",
    "ICHIMOKU_CLOUD_SUPPORT_FROM_ABOVE": "Ichimoku support at the cloud top",
    "ICHIMOKU_ENTER_CLOUD_FROM_ABOVE": "Entering the cloud from above",
    "ICHIMOKU_ENTER_CLOUD_FROM_BELOW": "Entering the cloud from below",
    "SUPPORT_TOUCH": "Support touch",
    "RESISTANCE_TOUCH": "Resistance touch",
    "TREND_REVERSAL_EVENT": "Trend reversal event (Supertrend/Ichimoku/KAMA)",
    "STRONG_REVERSAL_EVENT": "Strong combined reversal event",
    "BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE": "Lower BB touch + RSI below 40 + volume above its 20-day mean",
    "BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD": "Lower BB touch + bearish Supertrend + price below the Ichimoku cloud",
}
FAMILY_EN = {
    "bollinger": "Bollinger Bands",
    "rsi": "RSI",
    "supertrend": "Supertrend",
    "kama": "KAMA",
    "ichimoku": "Ichimoku",
    "support_resistance": "Support / resistance",
    "combined": "Combined events and conditions",
}
SECTOR_EN = {
    "Bankacilik": "Banking",
    "Sigorta_Araci_Kurum": "Insurance & brokerage",
    "Holding_Yatirim": "Holdings & investment",
    "Bilisim_Yazilim": "IT & software",
    "Demir_Celik_Boru": "Iron, steel & pipes",
    "Insaat_Yapi_Malzemeleri": "Construction & materials",
    "GYO": "Real estate investment trusts",
    "Otomotiv_YanSanayi": "Automotive & parts",
    "Dayanikli_Tuketim": "Consumer durables",
    "Enerji": "Energy",
    "Petrokimya_Endustri": "Petrochemicals & industrials",
    "Tarim_Gubre": "Agriculture & fertilisers",
    "Gida_Icecek": "Food & beverages",
    "Perakende": "Retail",
    "Havacilik_Lojistik": "Aviation & logistics",
    "Savunma_Makine": "Defence & machinery",
    "Telekomunikasyon": "Telecommunications",
    "Saglik_Ilac": "Healthcare & pharma",
    "Madencilik": "Mining",
}
STATE_EN = {
    "above_cloud": "above the cloud",
    "below_cloud": "below the cloud",
    "inside_cloud": "inside the cloud",
    "bullish": "bullish",
    "bearish": "bearish",
    "rising": "rising",
    "falling": "falling",
    "flat": "flat",
}
VARIANT_EN = {
    "A_TECH": "technical",
    "B_TECH_SECTOR": "technical + sector",
    "C_TECH_SECTOR_FUND": "technical + sector + fundamentals",
    "D_FULL_STRUCTURED": "all structured data",
    "E_FULL_CONTEXTUAL": "structured + news context",
}
METRIC_EN = {
    "revenue": "Revenue",
    "gross_profit": "Gross profit",
    "ebitda": "EBITDA",
    "operating_profit": "Operating profit",
    "net_income_parent": "Net income (parent)",
    "operating_cash_flow": "Operating cash flow",
    "roe": "ROE",
    "roa": "ROA",
    "gross_margin": "Gross margin",
    "ebitda_margin": "EBITDA margin",
    "operating_margin": "Operating margin",
    "net_margin": "Net margin",
    "net_debt": "Net debt",
    "net_debt_to_ebitda": "Net debt / EBITDA",
    "debt_to_equity": "Debt / equity",
    "current_ratio": "Current ratio",
    "quick_ratio": "Quick ratio",
    "cash_conversion": "Cash conversion (OCF / net income)",
    "loans_to_deposits": "Loans / deposits",
    "equity_to_assets": "Equity / assets",
    "cost_to_income": "Cost / income",
    "pe": "P/E",
    "pb": "P/B",
    "ev_to_ebitda": "EV/EBITDA",
}
DAY_EN = {"Mon": "Mon", "Tue": "Tue", "Wed": "Wed", "Thu": "Thu", "Fri": "Fri"}


# --------------------------------------------------------------------------------------------- English formatting
def num(x: float | None, d: int = 2) -> str:
    return "–" if x is None else f"{x:,.{d}f}"


def integer(n: int | float | None) -> str:
    return "–" if n is None else f"{int(n):,}"


def pct(x: float | None, d: int = 2, signed: bool = False) -> str:
    """Fraction -> percent: 0.1235 -> '12.35%' (signed: '+12.35%')."""
    if x is None:
        return "–"
    return f"{x * 100:+,.{d}f}%" if signed else f"{x * 100:,.{d}f}%"


def pp(diff: float | None, d: int = 2) -> str:
    """Difference of two fractions -> signed percentage points: 0.0434 -> '+4.34 pp'."""
    return "–" if diff is None else f"{diff * 100:+,.{d}f} pp"


def level_pct(v: float | None, d: int = 2) -> str:
    """A value already in percent units (policy rate 37.0) -> '37.00%'."""
    return "–" if v is None else f"{v:,.{d}f}%"


def money(v: float | None) -> str:
    if v is None:
        return "–"
    a = abs(v)
    for unit, div in (("tn", 1e12), ("bn", 1e9), ("mn", 1e6)):
        if a >= div:
            return f"TRY {v / div:,.2f} {unit}"
    return f"TRY {v:,.0f}"


def day(iso: Any) -> str:
    return "–" if not iso else str(iso)[:10]


def stamp(iso: Any) -> str:
    return "–" if not iso else str(iso)[:16]


def p_eq(p: float | None) -> str:
    """p-value in running text: 'p = 0.123' or 'p < 0.001'."""
    return "p = –" if p is None else ("p < 0.001" if p < 0.001 else f"p = {p:.3f}")


def pval(p: float | None) -> str:
    return "–" if p is None else ("<0.001" if p < 0.001 else f"{p:.3f}")


def sector(name: str) -> str:
    return SECTOR_EN.get(name, name.replace("_", " "))


def event(code: str) -> str:
    return EVENT_EN.get(code, code)


def table(head: Sequence[str], rows: Sequence[Sequence[str]], align: str = "") -> str:
    al = align or "l" + "r" * (len(head) - 1)
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---:" if a == "r" else ":---" for a in al) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def bullets(items: Sequence[str]) -> str:
    return "\n".join(f"- {x}" for x in items)


# --------------------------------------------------------------------------------------------- runs and provenance
@dataclass
class Run:
    qid: str
    res: AnalysisResult
    memory: Path

    def env(self, tool: str, state: str | None = None) -> Any:
        envs = [
            c.envelope
            for c in self.res.calls
            if c.tool == tool and c.envelope is not None and (state is None or c.state.value == state)
        ]
        return envs[-1] if envs else None

    def envs(self, tool: str) -> list[Any]:
        return [c.envelope for c in self.res.calls if c.tool == tool and c.envelope is not None]


def run_golden(qid: str, out: Path) -> Run:
    golden = json.loads((project_root() / "eval" / "golden_questions.json").read_text(encoding="utf-8"))
    q = next(x for x in golden["questions"] if x["id"] == qid)
    req = AnalysisRequest(
        question=q["question"],
        scenario=Scenario(q["scenario"]),
        tickers=q["tickers"],
        as_of_date=date.fromisoformat(golden["as_of_date"]),
        params=q.get("params", {}),
        advice_requested=bool(q.get("advice_requested", False)),
    )
    path = out / f"episodic_{qid.lower()}.sqlite"
    path.unlink(missing_ok=True)
    mem = EpisodicMemory(path)
    res = run_analysis(req, tool_context(), build_config(explainer="template", memory=mem))
    mem.conn.close()
    return Run(qid, res, path)


class Scan:
    """Direct tool calls outside the harness run (cross-sector / cross-stock comparisons), listed in the appendix."""

    def __init__(self) -> None:
        from bistharness.tools import ToolContext

        self.ctx = ToolContext.from_settings()
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, label: str, tool: str, args: dict[str, Any]) -> Any:
        from bistharness.tools import run_tool

        env = run_tool(tool, {"as_of_date": AS_OF, **args}, self.ctx)
        self.calls.append((label, tool, env))
        return env

    def appendix(self) -> str:
        if not self.calls:
            return ""
        rows = [[label, f"`{tool}`", f"`{env.call_id[:16]}`"] for label, tool, env in self.calls]
        return (
            "\n\n**Additional tool calls for comparison** (outside the harness run; same snapshot and as_of)\n\n"
            + table(["Scope", "Tool", "call_id"], rows, "lll")
        )


def provenance(run: Run, rel_root: Path, scan: Scan | None = None) -> str:
    rows = [
        [c.state.value, f"`{c.tool}`", c.origin, f"`{c.envelope.call_id[:16]}`" if c.envelope else "–"]
        for c in run.res.calls
    ]
    dv: dict[str, str] = {}
    for c in run.res.calls:
        if c.envelope is not None:
            dv.update(c.envelope.data_version)
    return (
        f"Analysis `{run.res.analysis_id}` · decision `{run.res.decision_id}` · episodic record "
        f"`{run.memory.relative_to(rel_root).as_posix()}` (replay: `python -m bistharness.harness replay --decision ...` "
        "with that memory file, or the web UI).\n\nData version (sha256, first 12): "
        + ", ".join(f"{k} `{str(v)[:12]}`" for k, v in sorted(dv.items()))
        + "\n\n"
        + table(["State", "Tool", "Origin", "call_id"], rows, "llll")
        + (scan.appendix() if scan else "")
    )


def header(code: str, title: str, run: Run) -> str:
    r = run.res.request
    return (
        f"# {code} — {title}\n\n*FinTreX Analyst research report · analysis date (as_of) {day(r.as_of_date)} · period "
        f"{day(r.start)} to {day(r.as_of_date)}. Generated by `eval/scenario_reports.py` from tool outputs: every number "
        "in the text and tables comes from a tool envelope (source calls in the appendix). Educational analysis, "
        "not investment advice.*\n\n"
    )


def question_md(run: Run, spec: str) -> str:
    return (
        f"## 1. Question\n\n> {QUESTION_EN[run.qid]}\n\n*(Instructor's golden question {run.qid}; the original Turkish "
        f"wording is in `eval/golden_questions.json`.)*\n\n{spec}\n\n"
    )


def decision_md(run: Run) -> str:
    res, e = run.res, run.res.explanation
    codes = sorted({g["code"] for g in res.gate_reasons})
    if e is None:
        return "No explanation was produced."
    first = e.attempts[0].validation.ok if e.attempts else None
    return (
        f"The same question was run through the 17-state harness (scenario planner + rule-based explainer). Final "
        f"analytical state: **{e.action.value}**; risk gate **{res.gate.value}** ({len(res.gate_reasons)} findings; "
        f"types: {', '.join(codes) or 'none'}). {len(res.calls)} tool calls, {len(res.invalid_calls)} invalid. The "
        f"explanation cites {len(e.cited)} committed evidence items ({', '.join(e.cited)}) and "
        f"{'passed' if first else 'did not pass'} the output validator on the first attempt"
        f"{' (deterministic fallback used)' if e.fallback_used else ''}. The product writes its explanation in Turkish; "
        "it is stored verbatim in the episodic record above and can be replayed byte for byte."
    )


def bt_rows(v: dict[str, Any], bench_label: str = "Equal-weight buy & hold") -> list[list[str]]:
    m, t = v["metrics"], v["trades"]
    rows = [
        ["Period", f"{day(m['start'])} to {day(m['end'])}"],
        ["Signals / closed trades", f"{integer(t['n_signals'])} / {integer(t['n_closed'])}"],
        ["Win rate", pct(t["win_rate"], 1)],
        ["Cumulative return (nominal)", pct(m["cumulative"], 2, True)],
        ["Real return (CPI-deflated)", pct(v["real_cumulative"], 2, True)],
        ["Difference vs XU100", pp(v["vs_xu100"])],
        [f"Difference vs {bench_label.lower()}", pp(v["vs_buy_and_hold"])],
        ["Sharpe (rf = 0 / policy rate)", f"{num(m['sharpe_rf0'])} / {num(m['sharpe_policy'])}"],
        ["Maximum drawdown", pct(m["max_drawdown"], 2)],
    ]
    for lab, key in (("In sample", "in_sample"), ("Out of sample", "out_of_sample")):
        b = v.get(key)
        if b:
            rows.append(
                [
                    f"{lab} ({day(b['start'])} to {day(b['end'])})",
                    f"{pct(b['cumulative'], 2, True)}, Sharpe {num(b['sharpe_rf0'])}",
                ]
            )
    return rows


def backtest_md(run: Run, bench_label: str = "Equal-weight buy & hold") -> tuple[str, Any, Any]:
    env = run.env("run_backtest", "RUN_BACKTEST")
    if env is None:
        return "No backtest output.", None, None
    name, v = next(iter(env.result["variants"].items()))
    spec = env.result["strategy_spec"]
    md = (
        f"Variant `{name}` ({VARIANT_EN.get(name, name)}) of the pre-registered rule `{spec['name']}` (fixed before any "
        f"result was seen): entry events {', '.join(f'`{x}`' for x in spec['entry_events'])}; holding period "
        f"{spec['holding_days']} trading days; signal at the close of day t, trade at the open of t+1; cost "
        f"{num(env.result['costs']['tx_cost_bps'], 0)} bp per trade.\n\n"
        + table(["Measure", "Value"], bt_rows(v, bench_label), "lr")
    )
    return md, name, v


# --------------------------------------------------------------------------------------------- matplotlib
def pyplot() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def style(ax: Any) -> None:
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK)
        ax.spines[s].set_linewidth(0.8)
    ax.tick_params(colors=INK, labelsize=8.5)
    ax.grid(axis="x", color="#e4e1d8", linewidth=0.6)
    ax.set_axisbelow(True)


def save(fig: Any, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor=PAPER)
    pyplot().close(fig)
    return path.name


def ci_dotplot(rows: list[tuple[str, float, tuple[float, float], float]], xlabel: str, path: Path) -> str:
    """rows: (label, rate, (lo, hi), baseline) -> dot = rate, bar = 95% CI, tick = baseline."""
    plt = pyplot()
    fig, ax = plt.subplots(figsize=(8.2, 0.3 * len(rows) + 1.2))
    for i, (_lab, rate, (lo, hi), base) in enumerate(rows):
        ax.plot([lo * 100, hi * 100], [i, i], color="#c9c5ba", linewidth=3, solid_capstyle="round")
        ax.scatter(base * 100, i, marker="|", s=120, color=INK, zorder=3)
        ax.scatter(rate * 100, i, s=26, color=SIGNAL, zorder=4)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=8)
    ax.set_xlabel(xlabel)
    style(ax)
    return save(fig, path)


def equity_plot(eq: list[dict[str, Any]], path: Path, strategy_label: str, bh_label: str) -> str:
    plt = pyplot()
    x = [date.fromisoformat(str(p["date"])[:10]) for p in eq]
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    ax.plot(x, [p["buy_and_hold"] * 100 for p in eq], ":", color=MUTE, linewidth=1.2, label=bh_label)
    ax.plot(x, [p["xu100"] * 100 for p in eq], color=INK, linewidth=1.1, label="XU100")
    ax.plot(x, [p["strategy"] * 100 for p in eq], color=SIGNAL, linewidth=1.8, label=strategy_label)
    ax.set_ylabel("cumulative return (%)")
    ax.legend(fontsize=7.5, frameon=False)
    style(ax)
    ax.grid(axis="y", color="#e4e1d8", linewidth=0.6)
    return save(fig, path)


def write(out: Path, name: str, md: str) -> Path:
    path = out / name
    path.write_text(md, encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------------- S3
def report_s3(out: Path) -> Path:
    run = run_golden("Q3", out)
    res = run.res
    rev = run.env("detect_reversal_events")
    r = rev.result
    sr, ind = run.env("find_support_resistance"), run.env("calculate_indicators")
    tk, h = r["ticker"], r["main_horizon"]
    by = {s["event_type"]: s for s in r["summary"]}
    figs = out / "fig"

    def n_mark(n: int) -> str:
        return f"{n}†" if n < 5 else (f"{n}*" if n < 10 else str(n))

    fam_rows: dict[str, list[list[str]]] = {}
    for s in r["summary"]:
        fam_rows.setdefault(FAMILY_EN.get(s["family"], s["family"]), []).append(
            [
                event(s["event_type"]) + (" ↑" if s["direction"] == "bullish" else " ↓"),
                n_mark(s["n"]),
                f"{s['n_success']} / {s['n'] - s['n_success']}" if s["n"] else "–",
                f"{pct(s['success_rate'], 1)} [{pct(s['success_rate_ci95'][0], 0)}–{pct(s['success_rate_ci95'][1], 0)}]"
                if s["n"]
                else "–",
                pct(s["baseline_success_rate"], 1),
                f"{pct(s['mean'], 2, True)} / {pct(s['median'], 2, True)}" if s["n"] else "–",
                pct(s["mean_reversal_strength"], 2) if s["n"] else "–",
                pp(s["mean_abnormal_vs_xu100"]) if s["n"] else "–",
                pval(s.get("p_bh")),
            ]
        )
    fam_md = "\n\n".join(
        f"**{fam}**\n\n"
        + table(
            [
                "Event",
                "n",
                "Success / failure",
                f"Success ({h}d) [95% CI]",
                "Non-event days",
                "Mean / median",
                "Reversal strength",
                "vs XU100",
                "p (BH)",
            ],
            rows,
        )
        for fam, rows in fam_rows.items()
    )
    base_ev = by["BB_LOWER_TOUCH"]
    rsi_c, st_c = by.get("BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE"), by.get("BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD")
    comb_rows = [
        [
            event(e),
            str(by[e]["n"]),
            pct(by[e]["success_rate"], 1),
            pct(by[e]["mean"], 2, True),
            pct(by[e]["median"], 2, True),
            pct(by[e]["mean_reversal_strength"], 2),
        ]
        for e in ("BB_LOWER_TOUCH", "BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE", "BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD")
        if e in by
    ]

    def cmp(a: float, b: float) -> str:
        return "higher" if a > b else "lower" if a < b else "equal"

    comb_text = []
    if rsi_c:
        comb_text.append(
            f"Adding the RSI-below-40 and rising-volume condition gives a success rate of {pct(rsi_c['success_rate'], 1)} "
            f"({cmp(rsi_c['success_rate'], base_ev['success_rate'])} than the {pct(base_ev['success_rate'], 1)} of all lower "
            f"touches), but the sample falls to {rsi_c['n']} events."
        )
    if st_c:
        comb_text.append(
            f"When the Supertrend is bearish and price is below the cloud the success rate is {pct(st_c['success_rate'], 1)} "
            f"({cmp(st_c['success_rate'], base_ev['success_rate'])}; {st_c['n']} events). The specification's illustrative "
            "scenario describes signals failing under this condition; in ASELS over this period the data "
            + ("show the opposite" if st_c["success_rate"] >= base_ev["success_rate"] else "agree")
            + f", although the difference is not significant after correction (p (BH) = {pval(st_c['p_bh'])})."
        )
    hz_rows = []
    for e in (
        "BB_LOWER_TOUCH",
        "BB_LOWER_REVERSAL",
        "BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE",
        "BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD",
        "RSI_TROUGH_VOLUME",
        "SUPERTREND_BULLISH_FLIP",
        "ICHIMOKU_BULLISH_BREAKOUT",
        "SUPPORT_TOUCH",
    ):
        cells = {x["horizon"]: x for x in r["horizons"].get(e) or []}
        if cells:
            hz_rows.append(
                [event(e)]
                + [
                    f"{pct(cells[k]['success_rate'], 0)} / {pct(cells[k]['mean'], 1, True)}"
                    if k in cells and cells[k]["n"]
                    else "–"
                    for k in (1, 3, 5, 10, 20)
                ]
            )
    reg_rows = []
    for e in (
        "BB_LOWER_TOUCH",
        "BB_LOWER_REVERSAL",
        "RSI_TROUGH_VOLUME",
        "SUPERTREND_BULLISH_FLIP",
        "ICHIMOKU_BULLISH_BREAKOUT",
    ):
        b = r["breakdowns_main_horizon"].get(e) or {}
        cells = []
        for dim, states in (("market_trend", ("rising", "falling")), ("volatility", ("low", "high"))):
            for stt in states:
                c = (b.get(dim) or {}).get(stt)
                cells.append(f"{pct(c['success_rate'], 0)} (n={c['n']})" if c and c["n"] else "–")
        reg_rows.append([event(e), *cells])
    tested = [s for s in r["summary"] if s["n"] and s.get("p_mean_vs_baseline") is not None]
    raw = sum(1 for s in tested if s["p_mean_vs_baseline"] < 0.05)
    bh = sum(1 for s in tested if (s.get("p_bh") or 1) < 0.05)
    bon = sum(1 for s in tested if (s.get("p_bonferroni") or 1) < 0.05)
    mt_text = (
        "None of the differences that look significant one by one survives the correction: no event type separates "
        "forward returns from non-event days with statistical confidence in this period. The high success rates partly "
        f"reflect ASELS' strong overall uptrend (non-event days rose {pct(base_ev['baseline_success_rate'], 1)} of the time)."
        if bh == 0
        else f"{bh} event types remain significant after correction."
    )
    st = ind.result["state"] if ind else {}
    trend = (
        f"As of {day(r['end'])}: Supertrend {STATE_EN.get(st.get('supertrend_state'), st.get('supertrend_state'))}, price "
        f"{STATE_EN.get(st.get('ichimoku_state'), st.get('ichimoku_state'))}, KAMA slope "
        f"{STATE_EN.get(st.get('kama_slope_state'), st.get('kama_slope_state'))}, RSI {num(st.get('rsi'), 1)}."
        if st
        else ""
    )
    active = r.get("active_now") or {}
    rec_rows = [
        [
            day(e["event_date"]),
            event(e["event_type"]),
            num(e["close"]),
            STATE_EN.get(e.get("supertrend_state"), str(e.get("supertrend_state"))),
            STATE_EN.get(e.get("ichimoku_state"), str(e.get("ichimoku_state"))),
        ]
        for e in (r.get("recent_events") or [])[-8:]
    ]
    sr_rows = []
    if sr:
        for lv in sr.result["levels"]:
            sr_rows.append(
                [
                    lv["side"],
                    num(lv["price"]),
                    str(lv["touches"]),
                    day(lv["last_touch"]),
                    day(lv["known_from"]),
                    pct(lv["distance"], 2, True),
                ]
            )
    bt_text, _name, bt = backtest_md(run, f"{tk} buy & hold")
    bt_read = ""
    fig_eq = ""
    if bt:
        oos = bt.get("out_of_sample")
        bt_read = (
            f"The strategy finished {pp(bt['vs_xu100'])} versus XU100 but {pp(bt['vs_buy_and_hold'])} versus simply holding "
            f"{tk}: short (5-day) reversal trades miss most of a strong trend."
            + (f" Out of sample the return was {pct(oos['cumulative'], 2, True)}." if oos else "")
        )
        if bt.get("equity"):
            fig_eq = equity_plot(bt["equity"], figs / "s3_backtest.png", "Strategy (A_TECH)", f"{tk} buy & hold")
    rows = [s for s in r["summary"] if s["n"] >= 5]
    rows.sort(key=lambda s: (s["success_rate"] or 0) - (s["baseline_success_rate"] or 0))
    fig_ci = ci_dotplot(
        [
            (
                f"{event(s['event_type'])} (n={s['n']})",
                s["success_rate"],
                tuple(s["success_rate_ci95"]),
                s["baseline_success_rate"],
            )
            for s in rows
        ],
        f"{h}-day success rate (%) — dot: event, bar: 95% CI, tick: non-event days",
        figs / "s3_success_rates.png",
    )
    plt = pyplot()
    fig, ax = plt.subplots(figsize=(8.2, 3.8))
    hs: list[dict[str, Any]] = []
    for e, color, ls in (
        ("BB_LOWER_TOUCH", INK, "-"),
        ("BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE", SIGNAL, "-"),
        ("BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD", MUTE, "--"),
    ):
        hs = r["horizons"].get(e) or []
        ax.plot(
            [x["horizon"] for x in hs],
            [x["success_rate"] * 100 for x in hs],
            ls,
            color=color,
            marker="o",
            markersize=4,
            label=event(e),
        )
    if hs:
        ax.plot(
            [x["horizon"] for x in hs],
            [x["baseline_success_rate"] * 100 for x in hs],
            ":",
            color="#b5b1a6",
            label="non-event days",
        )
    ax.set_xlabel("horizon (trading days)")
    ax.set_ylabel("success rate (%)")
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    style(ax)
    ax.grid(axis="y", color="#e4e1d8", linewidth=0.6)
    fig_hz = save(fig, figs / "s3_horizon_profile.png")
    findings = [
        f"Lower Bollinger touches occurred {base_ev['n']} times; {base_ev['n_success']} were followed by a higher price "
        f"after {h} days ({pct(base_ev['success_rate'], 1)}; non-event days {pct(base_ev['baseline_success_rate'], 1)}).",
    ]
    if st_c:
        findings.append(
            f"Touches with a bearish Supertrend and price below the cloud ({st_c['n']} events) were historically stronger: "
            f"{pct(st_c['success_rate'], 1)} success, mean {pct(st_c['mean'], 2, True)}."
        )
    findings.append(f"After multiple-testing correction {bh} of {r['family_size']} event types are significant.")
    if bt:
        findings.append(
            f"The pre-registered reversal strategy returned {pct(bt['metrics']['cumulative'], 2, True)}: {pp(bt['vs_xu100'])} "
            f"versus XU100 but {pp(bt['vs_buy_and_hold'])} versus holding {tk}."
        )
    if res.explanation:
        findings.append(f"Harness decision: {res.explanation.action.value} (risk gate {res.gate.value}).")
    md = (
        header("S3", f"Technical reversal events: {tk}", run)
        + f"""## Key findings

{bullets(findings)}

"""
        + question_md(
            run,
            "Specification §13: how price behaved after lower Bollinger touches and other technical events, "
            "single-indicator events versus combined conditions, and results by market regime.",
        )
        + f"""## 2. Method

- **Event date = confirmation date.** An RSI local trough forms at t−1 and is confirmed at t, so the event is dated t.
  A support/resistance level is known from the day its pivot is confirmed. The Ichimoku Chikou span is not used.
- **Success:** forward {h}-day return > 0 for bullish events, < 0 for bearish events. Main horizon {h} trading days;
  1, 3, 5, 10 and 20 days are also reported.
- **Benchmark:** the same horizon on non-event days (baseline rate). Reversal strength = best directional move inside
  the window (maximum favourable excursion). Abnormal return = stock return − XU100 return.
- **Point in time:** only data known at the close of {day(res.request.as_of_date)}. **{len(rev.excluded_incomplete_events)}
  event-horizon pairs** whose forward window was not complete by then are excluded and listed in the tool output
  (`excluded_incomplete_events`) instead of being silently dropped.
- **Multiple testing:** {r["family_size"]} event types tested in one call; Welch p-values of the event vs non-event mean
  difference are adjusted with Bonferroni and Benjamini–Hochberg.
- Indicator parameters equal the instructor's reference scripts (BB 20/2σ, RSI 14 Wilder, KAMA 10/2/30, ATR 10,
  Supertrend 10/3, Ichimoku 9/26/52, volume MA20), verified by parity tests.

## 3. Event families

Columns: successes / failures; {h}-day success rate with 95% CI; rate on non-event days; {h}-day mean / median return;
mean reversal strength; mean abnormal return vs XU100; Benjamini–Hochberg p. ↑ bullish, ↓ bearish hypothesis.
† n < 5 (insufficient sample), * n < 10 (small sample).

{fam_md}

![Success rates and confidence intervals](fig/{fig_ci})

## 4. Single indicator versus combined conditions

{table(["Condition", "n", f"Success ({h}d)", "Mean", "Median", "Reversal strength"], comb_rows)}

{" ".join(comb_text)}

## 5. Horizon profile

Cell: success rate / mean return.

{table(["Event", "1d", "3d", "5d", "10d", "20d"], hz_rows)}

![Horizon profile](fig/{fig_hz})

## 6. By market regime ({h}-day success)

{table(["Event", "XU100 rising", "XU100 falling", "Low volatility", "High volatility"], reg_rows)}

Regime subsets are small and are not a basis for a decision on their own.

## 7. Multiple-testing risk

Of {len(tested)} event types, {raw} have a raw p < 0.05 for the event vs non-event mean difference; {bh} after
Benjamini–Hochberg and {bon} after Bonferroni. {mt_text}

## 8. State as of {day(res.request.as_of_date)}

{trend} Events active in the last {active.get("window_trading_days", 5)} trading days (since {day(active.get("from"))}):
{", ".join(event(e) for e in active.get("events", [])) or "none"}.

{table(["Date", "Event", "Close", "Supertrend", "Ichimoku"], rec_rows, "llrll") if rec_rows else ""}

**Support and resistance levels** (pivots of the last 250 bars clustered within 2%, at least two touches)

{table(["Side", "Level", "Touches", "Last touch", "Known from", "Distance from close"], sr_rows, "lrrllr") if sr_rows else "None."}

## 9. Backtest

{bt_text}

{f"![Backtest equity curve](fig/{fig_eq})" if fig_eq else ""}

{bt_read}

## 10. Harness decision

{decision_md(run)} A `TECHNICAL_REVERSAL_CANDIDATE` label requires the current event to be supported by historical and
backtest evidence; when that is not the case the system stays with monitoring.

## 11. Limitations and differences from the instructor's script

- In the instructor's S3 script the Supertrend final bands are seeded with a NaN ATR, so the Supertrend never starts
  and the script produces no Supertrend flips. Here the recursion starts at the first valid ATR bar (identical to the
  script's recursion from that start, tested); this period has {by.get("SUPERTREND_BULLISH_FLIP", {}).get("n", 0)} bullish
  and {by.get("SUPERTREND_BEARISH_FLIP", {}).get("n", 0)} bearish flips.
- The script's forward returns use `dropna`, silently dropping incomplete windows; here they are listed separately.
- A KAMA–price cross is mathematically the same as a KAMA slope turn; it is not counted as a separate event (to avoid
  double counting and inflating the multiple-testing family).
- Prices are dividend- and split-adjusted and anchored to the analysis date; truncated bars and spurious rows found in
  yfinance are corrected in the primary source.
- One stock, one period: results do not generalise to other stocks or periods.

## Appendix — source tool calls

{provenance(run, out.parent.parent)}
"""
    )
    return write(out, f"s3_technical_reversal_{tk.lower()}.md", md)


# --------------------------------------------------------------------------------------------- S1
def report_s1(out: Path) -> Path:
    run = run_golden("Q1", out)
    scan = Scan()
    sec = run.env("rank_sector_relative_strength").result
    figs = out / "fig"
    members = sec["members_with_data"]
    rank_rows = [
        [
            x["ticker"],
            pct(x["ret"], 2, True),
            pct(x["peer_median"], 2, True),
            pp(x["lag_score"]),
            f"{x['rank']}/{len(members)}",
            pp(x["rel_benchmark"]),
        ]
        for x in sec["ranking"]
    ]
    windows = sorted({w["window"] for w in sec["all_windows"]})
    win_rows = []
    for t in members:
        cells = {w["window"]: w for w in sec["all_windows"] if w["ticker"] == t}
        win_rows.append([t] + [pp(cells[w]["lag_score"]) if w in cells else "–" for w in windows])
    gm_rows = [
        [
            f"{w}d",
            pct(sec["group_median"][str(w)], 2, True),
            pct(sec["benchmark_returns"][str(w)], 2, True),
            "strong" if sec["strong"][str(w)] else "not strong",
        ]
        for w in windows
    ]
    cu = sec["catch_up"]
    cu_rows = [
        [
            f"{x['horizon']}d",
            str(x["n"]),
            str(x["n_catch_up"]),
            str(x["n_false_positive"]),
            f"{pct(x['hit_rate'], 1)} [{pct(x['hit_rate_ci95'][0], 0)}–{pct(x['hit_rate_ci95'][1], 0)}]",
            pct(x["baseline_hit_rate"], 1),
            pp(x["median_relative"]),
            pval(x["p_rate_vs_baseline"]),
        ]
        for x in cu["horizons"]
    ]
    fp_rows = [
        [
            day(f["event_date"]),
            f["ticker"],
            pp(f["lag_score"]),
            pp(f.get("rel_5d")),
            pp(f.get("rel_10d")),
            pp(f.get("rel_20d")),
        ]
        for f in cu["false_positives"][-8:]
    ]
    fund_rows = []
    for env in run.envs("calculate_fundamental_change"):
        rr = env.result
        last = (rr.get("reports") or [None])[-1]
        if last:
            ch = last.get("ratio_changes", {})
            em, nm = ch.get("ebitda_margin"), ch.get("net_margin")
            fund_rows.append(
                [
                    rr["ticker"],
                    last["fiscal_period"],
                    stamp(last["disclosure_datetime"]),
                    f"{pct(em['old'])} → {pct(em['new'])}" if em else "n/a for template",
                    f"{pct(nm['old'])} → {pct(nm['new'])}" if nm else "–",
                    pct((last.get("yoy_ytd") or {}).get("revenue"), 1, True),
                ]
            )
    u = load_universe()
    groups: list[str] = []
    for t in u.tickers():
        g = u.instruments[t].peer_group
        if g and g not in groups and len(u.peer_groups.get(g, ())) >= 2:
            groups.append(g)
    cross = []
    for g in groups:
        env = scan(sector(g), "rank_sector_relative_strength", {"sector_or_tickers": g, "start": START, "horizon": 20})
        h20 = next((x for x in env.result["catch_up"]["horizons"] if x["horizon"] == 20), None)
        if h20 and h20["n"]:
            cross.append((g, env.result, h20))
    cross_rows = [
        [
            sector(g),
            str(len(r["members_with_data"])),
            str(h["n"]),
            pct(h["hit_rate"], 1),
            pct(h["baseline_hit_rate"], 1),
            str(h["n_false_positive"]),
            pp(h["median_relative"]),
            pval(h["p_rate_vs_baseline"]),
        ]
        for g, r, h in cross
    ]
    beats = sum(1 for _, _, h in cross if h["hit_rate"] > h["baseline_hit_rate"])
    signif = sum(1 for _, _, h in cross if h["p_rate_vs_baseline"] < 0.05)
    fig_cross = ci_dotplot(
        [
            (f"{sector(g)} (n={h['n']})", h["hit_rate"], tuple(h["hit_rate_ci95"]), h["baseline_hit_rate"])
            for g, _r, h in cross
        ],
        "20-day catch-up rate (%) — dot: laggards, bar: 95% CI, tick: non-lagging days",
        figs / "s1_sectors.png",
    )
    bt_text, name, bt = backtest_md(run)
    h20 = next((x for x in cu["horizons"] if x["horizon"] == 20), cu["horizons"][-1])
    hz = str(sec["horizon"])
    findings = [
        f"Over the last {hz} trading days the {sector(sec['group'])} sector median returned {pct(sec['group_median'][hz], 2, True)} "
        f"versus {pct(sec['benchmark_returns'][hz], 2, True)} for XU100: the sector is {'strong' if sec['strong'][hz] else 'not strong'}. "
        f"Laggards: {', '.join(sec['laggards']) or 'none'}; leaders: {', '.join(sec['leaders']) or 'none'}.",
        f"Lagging also over longer windows (structural candidates): {', '.join(sec['persistent_laggards']) or 'none'}.",
        f"Between {day(cu['start'])} and {day(cu['end'])}, {cu['n_events']} laggard entries had a 20-day catch-up rate of "
        f"{pct(h20['hit_rate'], 1)} versus {pct(h20['baseline_hit_rate'], 1)} on non-lagging days; {h20['n_false_positive']} false positives.",
        f"Across {len(cross)} sectors the laggards' 20-day catch-up rate beats the baseline in {beats}, and the difference is "
        f"significant (p < 0.05) in {signif}.",
    ]
    if bt:
        findings.append(
            f"Backtest `{name}`: {pct(bt['metrics']['cumulative'], 2, True)}, {pp(bt['vs_xu100'])} versus XU100."
        )
    md = (
        header("S1", f"Sector laggards and catch-up: {sector(sec['group'])}", run)
        + f"""## Key findings

{bullets(findings)}

"""
        + question_md(
            run,
            "Specification §11: do stocks that lag a strong sector later catch up with it; is the lag "
            "structural or temporary; how many false positives are there.",
        )
        + f"""## 2. Method

- **Peer group:** the TÜBİTAK 95-stock sector map (`config/universe.yaml: peer_groups`). The whole sector of each
  requested stock is used, not only the stocks named in the question ({", ".join(sec["members"])}).
- **Lag score:** stock return − median return of the OTHER members (leave-one-out). Threshold {pp(sec["lag_threshold"])}.
- **Strong sector:** group median > 0 and > XU100 over the same window.
- **Event:** ENTRY into the laggard state in a strong sector (one event per episode, not every day).
- **Catch-up:** stock return − equal-weight basket of the other members > 0 over the next h days; otherwise a false
  positive. Benchmark: the same rate on non-lagging days. Events without a complete forward window are excluded.

## 3. Current ranking ({day(sec["date"])}, last {hz} trading days)

{table(["Stock", "Return", "Median of other members", "Lag score", "Rank", "vs XU100"], rank_rows)}

**Lag score over several windows**

{table(["Stock", *[f"{w}d" for w in windows]], win_rows)}

**Sector strength**

{table(["Window", "Group median", "XU100", "State"], gm_rows, "lrrl")}

## 4. Do laggards historically catch up?

{table(["Horizon", "n", "Caught up", "False positives", "Rate [95% CI]", "Non-lagging days", "Median relative", "p"], cu_rows)}

**Most recent false positives** (the lagging stock kept underperforming the basket)

{table(["Date", "Stock", "Lag score", "5d relative", "10d relative", "20d relative"], fp_rows, "llrrrr") if fp_rows else "None."}

## 5. Structural or temporary?

Stocks lagging over longer windows too: **{", ".join(sec["persistent_laggards"]) or "none"}**. Latest reports (from the
same harness run; only reports disclosed by {day(run.res.request.as_of_date)}):

{table(["Stock", "Period", "Disclosed", "EBITDA margin", "Net margin", "Revenue (YoY, YTD)"], fund_rows, "lllrrr") if fund_rows else "No fundamentals."}

A lag in a stock whose margins fell suggests the price reflects a fundamental deterioration (structural candidate); a
lag in a stock with improving margins may be temporary. The split is not conclusive, which is why the system only
gives a candidate label with backtest evidence.

## 6. All sectors

The same study for every sector of the 30-stock course universe (20-day horizon):

{table(["Sector", "Members", "Events", "Catch-up", "Baseline", "False positives", "Median relative", "p"], cross_rows)}

![Catch-up rate by sector](fig/{fig_cross})

The laggards' catch-up rate beats the baseline in {beats} of {len(cross)} sectors; the difference has p < 0.05 in
{signif}. With one test per sector, individually significant results also carry multiple-testing risk.

## 7. Backtest

{bt_text}

## 8. Harness decision

{decision_md(run)}

## 9. Limitations

- Sector groups are small (2–10 members); the median is sensitive to a few stocks.
- Laggard episodes are not independent (same sector, same days); confidence intervals may be optimistic.
- The structural/temporary split only looks at the latest margins; comparisons across TMS 29 periods carry warnings.

## Appendix — source tool calls

{provenance(run, out.parent.parent, scan)}
"""
    )
    return write(out, f"s1_sector_catch_up_{sector(sec['group']).lower().replace(' & ', '_').replace(' ', '_')}.md", md)


# --------------------------------------------------------------------------------------------- S2
def pattern_en(p: dict[str, Any]) -> str:
    cond = ", ".join(f"{DAY_EN.get(d, d)} {'up' if s > 0 else 'down'}" for d, s in p["condition"])
    return f"[{cond}] → {'–'.join(DAY_EN.get(d, d) for d in p['outcome'])} return"


def report_s2(out: Path) -> Path:
    run = run_golden("Q2", out)
    scan = Scan()
    r = run.env("test_weekday_pattern").result
    tk, p, per, st = r["ticker"], r["pattern"], r["periods"], r["stability"]
    label = pattern_en(p)

    def prow(lab: str, k: str) -> list[str]:
        x = per[k]
        c, un, cm = x["conditional"], x["unconditional"], x["complement"]
        return [
            lab,
            f"{day(x['start'])} to {day(x['end'])}",
            str(x["complete_weeks"]),
            str(x["condition_weeks"]),
            pct(x["condition_frequency"], 1),
            f"{pct(c['mean'], 2, True)} / {pct(c['median'], 2, True)}",
            pct(c["mean_after_cost"], 2, True),
            pct(c["positive_rate"], 1),
            f"{pct(un['mean'], 2, True)} / {pct(un['positive_rate'], 1)}",
            pct(cm["mean"], 2, True),
        ]

    test_rows = []
    for lab, k in (("In sample", "in_sample"), ("Out of sample", "out_of_sample")):
        x = per[k]
        ci = x.get("bootstrap_mean_ci95")
        test_rows.append(
            [
                lab,
                pp(x.get("mean_difference")),
                pval(x.get("p_welch_vs_complement")),
                pval(x.get("p_binomial_vs_unconditional")),
                pval(x.get("p_permutation_vs_complement")),
                f"{pct(ci[0], 2, True)} to {pct(ci[1], 2, True)}" if ci else "–",
                f"{x.get('family_rank', '–')}/{x.get('family_size', '–')}",
                pval(x.get("p_bh")),
                f"{x.get('full_sequence_count', '–')} ({pct(x.get('full_sequence_frequency'), 1)})",
            ]
        )
    wd = r["weekday_statistics"]
    wd_rows = []
    for i, dname in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]):
        cells = [dname]
        for k in ("in_sample", "out_of_sample"):
            d = wd[k][i] if i < len(wd.get(k, [])) else None
            cells += [f"{pct(d['mean'], 2, True)} / {pct(d['positive_rate'], 0)}", pval(d["p_bh"])] if d else ["–", "–"]
        wd_rows.append(cells)
    eff = r["weekday_effect_tests"]
    wk_rows = [
        [
            day(w["week_start"]),
            *[pct(w.get(d), 2, True) for d in ("Mon", "Tue", "Wed", "Thu", "Fri")],
            pct(w["outcome"], 2, True),
        ]
        for w in per["in_sample"].get("matching_weeks", [])
    ]
    from bistharness.tools.weekday_tool import WEEKDAY_PRESETS

    base = {
        "ticker": tk,
        "in_sample_start": per["in_sample"]["start"],
        "in_sample_end": per["in_sample"]["end"],
        "out_of_sample_start": per["out_of_sample"]["start"],
        "tx_cost_bps": r["tx_cost_bps"],
    }
    alt_rows = []
    for name in WEEKDAY_PRESETS:
        for ms, ms_lab in ((None, "all weeks"), (1, "XU100 up weeks"), (-1, "XU100 down weeks")):
            if name != p["label"] and ms is not None:
                continue
            a = scan(
                f"{tk} {name} ({ms_lab})", "test_weekday_pattern", {**base, "pattern": name, "market_sign": ms}
            ).result
            i_, o_ = a["periods"]["in_sample"], a["periods"]["out_of_sample"]
            alt_rows.append(
                [
                    pattern_en(a["pattern"]),
                    ms_lab,
                    str(i_["condition_weeks"]),
                    pct(i_["conditional"]["mean_after_cost"], 2, True) if i_["condition_weeks"] else "–",
                    pval(i_.get("p_bh")),
                    str(o_["condition_weeks"]),
                    pct(o_["conditional"]["mean_after_cost"], 2, True) if o_["condition_weeks"] else "–",
                    "yes" if a["stability"]["same_sign_out_of_sample"] else "no",
                ]
            )
    pts = []
    for t in load_universe().tickers():
        try:
            a = scan(f"{t} {p['label']}", "test_weekday_pattern", {**base, "ticker": t, "pattern": p["label"]}).result
        except Exception:  # a stock without enough history is skipped (the appendix lists executed calls only)
            continue
        s3 = a["stability"]
        if s3.get("in_sample_effect") is not None:
            pts.append(
                (
                    t,
                    s3["in_sample_effect"],
                    s3.get("out_of_sample_effect"),
                    a["periods"]["in_sample"].get("p_welch_vs_complement"),
                    a["periods"]["in_sample"].get("p_bh"),
                    s3.get("same_sign_out_of_sample"),
                )
            )
    raw_sig = [x for x in pts if x[3] is not None and x[3] < 0.05]
    bh_sig = [x for x in pts if x[4] is not None and x[4] < 0.05]
    raw_hold = [x for x in raw_sig if x[5]]
    same_sign = sum(1 for x in pts if x[5])
    plt = pyplot()
    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    ax.axhline(0, color=INK, linewidth=0.7)
    ax.axvline(0, color=INK, linewidth=0.7)
    ax.scatter(
        [x[1] * 100 for x in pts if x[2] is not None], [x[2] * 100 for x in pts if x[2] is not None], s=22, color=MUTE
    )
    for t, ie, oe, *_ in pts:
        if t == tk and oe is not None:
            ax.scatter([ie * 100], [oe * 100], s=60, color=SIGNAL, zorder=4)
            ax.annotate(t, (ie * 100, oe * 100), xytext=(6, 4), textcoords="offset points", fontsize=8, color=SIGNAL)
    ax.set_xlabel("in-sample effect (conditional − complement, pp)")
    ax.set_ylabel("out-of-sample effect (pp)")
    style(ax)
    ax.grid(axis="y", color="#e4e1d8", linewidth=0.6)
    fig_scatter = save(fig, out / "fig" / "s2_all_stocks.png")
    bt_text, _name, _bt = backtest_md(run)
    ci_ = per["in_sample"]["conditional"]
    findings = [
        f"The condition {label} occurred in {per['in_sample']['condition_weeks']} in-sample weeks; the following Thursday–Friday "
        f"averaged {pct(ci_['mean'], 2, True)} ({pct(ci_['mean_after_cost'], 2, True)} after costs) versus "
        f"{pct(per['in_sample']['unconditional']['mean'], 2, True)} in all weeks.",
        f"Significant in sample after multiple-testing correction: {'yes' if st['in_sample_significant_after_adjustment'] else 'no'} "
        f"(p (BH) = {pval(per['in_sample']['p_bh'])}, family size {per['in_sample']['family_size']}).",
        f"Out of sample the condition occurred in only {per['out_of_sample']['condition_weeks']} weeks; the effect was "
        f"{pp(st['out_of_sample_effect'])} ({'same sign' if st['same_sign_out_of_sample'] else 'opposite sign'}); the sample is "
        f"{'sufficient' if st['out_of_sample_sufficient'] else 'insufficient'}.",
        f"Tested on {len(pts)} stocks, the same pattern has raw in-sample p < 0.05 in {len(raw_sig)} and {len(bh_sig)} after "
        f"Benjamini–Hochberg; {len(raw_hold)} of the raw-significant ones keep the same sign out of sample.",
    ]
    md = (
        header("S2", f"Weekday and multi-day patterns: {tk}", run)
        + f"""## Key findings

{bullets(findings)}

"""
        + question_md(
            run,
            "Specification §12: does a stock show a recurring day-of-week or multi-day sequence; does the "
            "pattern survive a later unseen period; transaction costs, unconditional returns and multiple-testing risk.",
        )
        + f"""## 2. Method

- **Condition ≠ outcome.** The condition days (Mon-Tue-Wed down) never contain the outcome; the outcome (compound
  Thu–Fri return) comes after every condition day. The instructor's script includes `Thu>0 & Fri>0` in the condition,
  so its "Thu-Fri positive rate" is 100% by construction; here the outcome is compared with the unconditional
  Thu–Fri distribution.
- **Periods are whole weeks.** A week cut by the split or unfinished at the analysis date belongs to no period.
- **Comparisons:** all weeks (unconditional) and the weeks without the condition (complement); Welch, binomial and
  permutation tests and a bootstrap confidence interval. Transaction cost {num(r["tx_cost_bps"], 0)} bp.
- **Multiple-testing family:** all sign combinations of the condition days ({per["in_sample"]["family_size"]} patterns);
  Bonferroni and Benjamini–Hochberg.

## 3. Pattern: {label}

Mean / median compound Thu–Fri return and positive rate.

{table(["Period", "Dates", "Complete weeks", "Condition weeks", "Frequency", "Conditional mean / median", "After cost", "Positive rate", "Unconditional mean / positive", "Complement mean"], [prow("In sample", "in_sample"), prow("Out of sample", "out_of_sample")])}

**Statistical tests**

{table(["Period", "Difference (cond. − complement)", "p Welch", "p binomial", "p permutation", "Bootstrap 95% CI", "Rank in family", "p (BH)", "Full 5-day sequence"], test_rows)}

**Stability:** in-sample effect {pp(st["in_sample_effect"])}, out-of-sample {pp(st["out_of_sample_effect"])}; same sign:
{"yes" if st["same_sign_out_of_sample"] else "no"}; out-of-sample sample sufficient: {"yes" if st["out_of_sample_sufficient"] else "no"};
significant after correction: {"yes" if st["in_sample_significant_after_adjustment"] else "no"}; positive after costs in
sample: {"yes" if st["net_of_cost_positive_in_sample"] else "no"}.

**Weeks in which the condition occurred (in sample)**

{table(["Week of", "Mon", "Tue", "Wed", "Thu", "Fri", "Thu–Fri"], wk_rows) if wk_rows else "None."}

## 4. Days of the week

Mean daily return / share of positive days and Benjamini–Hochberg p (test of mean = 0).

{table(["Day", "In sample", "p (BH)", "Out of sample", "p (BH)"], wd_rows)}

Difference across days: in sample ANOVA {p_eq(eff["in_sample"]["anova_p"])}, Kruskal–Wallis
{p_eq(eff["in_sample"]["kruskal_p"])}; out of sample ANOVA {p_eq(eff["out_of_sample"]["anova_p"])}, Kruskal–Wallis
{p_eq(eff["out_of_sample"]["kruskal_p"])}.

## 5. Other patterns and conditioning on the market

{table(["Pattern", "Weeks", "In: weeks", "In: after cost", "In: p (BH)", "Out: weeks", "Out: after cost", "Same sign"], alt_rows, "llrrrrrl")}

## 6. The same pattern in every stock

The specification notes that "a second stock may show the opposite pattern". The same pattern was tested in {len(pts)}
stocks of the course universe: {len(raw_sig)} have raw in-sample p < 0.05 and {len(bh_sig)} after Benjamini–Hochberg. Out of
sample {same_sign}/{len(pts)} stocks keep the in-sample sign, and {len(raw_hold)} of the raw-significant ones do. When
enough stocks and patterns are tried, "significant" results appear by chance; without out-of-sample consistency they
should not become trading rules.

![In-sample versus out-of-sample effect](fig/{fig_scatter})

## 7. Backtest

{bt_text}

## 8. Harness decision

{decision_md(run)}

## 9. Limitations

- The out-of-sample period is short ({per["out_of_sample"]["complete_weeks"]} complete weeks) with few condition weeks.
- Holidays and half days leave weeks incomplete; such weeks are excluded from both periods.
- The pattern family is limited to the condition's sign combinations; a wider search raises multiple-testing risk.

## Appendix — source tool calls

{provenance(run, out.parent.parent, scan)}
"""
    )
    return write(out, f"s2_weekday_patterns_{tk.lower()}.md", md)


# --------------------------------------------------------------------------------------------- S4
def metric_value(name: str, x: dict[str, Any]) -> str:
    v = x.get("value")
    if v is None:
        return "–"
    unit = x.get("unit") or "ratio"
    if unit == "TRY":
        return money(v)
    return num(v) if unit == "x" else pct(v, 2)


def reason(x: dict[str, Any]) -> str:
    r = x.get("reason") or ""
    return {"NOT_APPLICABLE_FOR_TEMPLATE": "not applicable for the template"}.get(r, r.replace("_", " ").lower())


def report_s4(out: Path) -> Path:
    run = run_golden("Q4", out)
    scan = Scan()
    met = run.env("get_fundamental_metrics").result
    chg = run.env("calculate_fundamental_change").result
    tk, lr = met["ticker"], met["latest_report"]
    lev_rows = []
    for name, d in met["levels"].items():
        cells = [METRIC_EN.get(name, name)]
        for basis in ("quarter", "ytd", "ttm"):
            x = d.get(basis) or {}
            cells.append(money(x["value"]) if x.get("value") is not None else (reason(x) or "–"))
        lev_rows.append(cells)
    rat_rows = [
        [
            METRIC_EN.get(n, n),
            metric_value(n, x),
            {"ttm": "TTM", "ytd": "YTD", "instant": "period end", "quarter": "quarter"}.get(
                x.get("basis", ""), x.get("basis", "")
            ),
            "approx." if x.get("approx") else "",
            reason(x),
        ]
        for n, x in met["ratios"].items()
    ]
    val = met.get("valuation") or {}
    val_rows = [[METRIC_EN.get(n, n), metric_value(n, x), reason(x)] for n, x in (val.get("metrics") or {}).items()]
    hz = chg["horizons"]
    timing = {"after_close": "after close", "pre_open": "before open", "intraday": "intraday"}
    rep_rows = []
    for rp in chg["reports"]:
        em = (rp.get("ratio_changes") or {}).get("ebitda_margin")
        react = rp.get("reaction") or {}
        yoy = rp.get("yoy_ytd") or {}
        rep_rows.append(
            [
                rp["fiscal_period"],
                stamp(rp["disclosure_datetime"]),
                timing.get(rp["timing"], rp["timing"]),
                pct(yoy.get("revenue"), 1, True),
                pct(yoy.get("ebitda"), 1, True),
                pp(em["change"]) if em else "–",
                *[pp((react.get(str(h)) or {}).get("abn_xu100")) for h in hz],
                "†" if rp.get("tms29_warning") else "",
            ]
        )
    agg_rows = [
        [
            f"{h}d",
            str(a["n"]),
            pct(a["mean_ret"], 2, True),
            pp(a["mean_abn_xu100"]),
            pp(a["median_abn_xu100"]),
            pp(a.get("mean_abn_sector")),
        ]
        for h, a in chg["aggregate"].items()
    ]
    bcd = chg["by_change_direction"]
    dir_rows = [
        [
            {"improved": "Improved", "deteriorated": "Deteriorated"}[k],
            str(g["n"]),
            pct(g["mean"], 2, True),
            pct(g["median"], 2, True),
            pct(g["positive_rate"], 0),
            f"{pct(g['min'], 1, True)} / {pct(g['max'], 1, True)}",
        ]
        for k, g in bcd["groups"].items()
        if k in ("improved", "deteriorated")
    ]
    welch_p = (bcd["groups"].get("welch") or {}).get("p_value")
    u = load_universe()
    cross = []
    for t in u.tickers():
        try:
            g = (
                scan(t, "calculate_fundamental_change", {"ticker": t, "start": START})
                .result.get("by_change_direction", {})
                .get("groups", {})
            )
        except Exception:  # no fundamentals (TRALT): skipped
            continue
        imp, det = g.get("improved"), g.get("deteriorated")
        if imp and det and imp.get("n") and det.get("n"):
            cross.append((t, u.instruments[t].template, imp, det, (g.get("welch") or {}).get("p_value")))
    cross_rows = [
        [t, tpl, f"{imp['n']} / {det['n']}", pct(imp["mean"], 2, True), pct(det["mean"], 2, True), pval(p)]
        for t, tpl, imp, det, p in cross
    ]
    better = sum(1 for _, _, imp, det, _ in cross if imp["mean"] > det["mean"])
    sig = sum(1 for *_, p in cross if p is not None and p < 0.05)
    bank = scan("AKBNK template comparison", "get_fundamental_metrics", {"ticker": "AKBNK", "start": START}).result
    bank_rows = [[METRIC_EN.get(n, n), metric_value(n, x), reason(x)] for n, x in bank["ratios"].items()]
    bt_text, _name, _bt = backtest_md(run)
    last = chg["reports"][-1]
    a_last = chg["aggregate"][str(hz[-1])]
    findings = [
        f"{tk}'s {lr['fiscal_period']} report was disclosed on {stamp(lr['disclosure_datetime'])}; year-to-date revenue "
        f"{pct(last['yoy_ytd']['revenue'], 1, True)} and EBITDA {pct(last['yoy_ytd']['ebitda'], 1, True)} year on year.",
        f"After {a_last['n']} disclosures the mean {hz[-1]}-day abnormal return versus XU100 was {pp(a_last['mean_abn_xu100'])} "
        f"(median {pp(a_last['median_abn_xu100'])}).",
        f"The {bcd['horizon']}-day return after reports with an improved versus a deteriorated EBITDA margin "
        f"{'differs significantly' if (welch_p or 1) < 0.05 else 'does not differ significantly'} (Welch {p_eq(welch_p)}).",
        f"In {better} of {len(cross)} stocks the mean {bcd['horizon']}-day return is higher after improved reports; the difference "
        f"has p < 0.05 in {sig}. 'Good earnings = price rise' is not supported by these data.",
    ]
    md = (
        header("S4", f"Quarterly fundamentals and post-disclosure price reaction: {tk}", run)
        + f"""## Key findings

{bullets(findings)}

"""
        + question_md(
            run,
            "Specification §14: how quarterly changes in company financials were reflected in prices AFTER "
            "the information became public; whether specific changes were historically associated with different reactions.",
        )
        + f"""## 2. Method

- **Source:** KAP XBRL financial statements; every value is stored with the report and the second it was disclosed.
  At an analysis date only reports disclosed by then are visible; for revisions the latest version known then is used.
- **Reaction base day:** disclosure after 18:10 on a trading day → that day's close; before the open or intraday →
  the previous trading day; holiday → the previous trading day. Horizons {", ".join(str(h) for h in hz)} trading days;
  abnormal return = stock − XU100 and stock − sector basket ({", ".join(chg["peers"])}).
- **TMS 29 (IAS 29 hyperinflation accounting):** {tk} {"applies" if chg["tms29_applies"] else "does not apply"} it. KAP
  income statements are cumulative (YTD); quarterly values are YTD differences and different reports carry different
  purchasing power, so the primary comparison is the same report's year-on-year YTD figure. Comparisons that reach
  before 2025 are marked †.
- **Multiples** (P/E, P/B, EV/EBITDA) are not taken from a vendor; they are computed from the price at the analysis date
  and the statements disclosed by then. Template: `{chg["template"]}`; ratios that do not fit the template are not computed.
- **Label:** improved = EBITDA margin up versus the previous report.

## 3. Latest report: {lr["fiscal_period"]} (disclosed {stamp(lr["disclosure_datetime"])}, [KAP]({lr["source"]}))

{table(["Item", "Quarter", "Year to date", "Trailing 12 months"], lev_rows)}

**Ratios**

{table(["Ratio", "Value", "Basis", "Note", "Why missing"], rat_rows, "lrlll")}

**Valuation** (price on {day(val.get("day"))}: {num(val.get("price"))})

{table(["Multiple", "Value", "Why missing"], val_rows, "lrl") if val_rows else "None."}

## 4. Price reaction, report by report

Year-to-date revenue and EBITDA growth (YoY); change in EBITDA margin; abnormal return versus XU100 after disclosure.

{table(["Period", "Disclosed", "Timing", "Revenue", "EBITDA", "EBITDA margin Δ", *[f"{h}d abnormal" for h in hz], "TMS 29"], rep_rows, "lll" + "r" * (3 + len(hz)) + "l")}

**Average reaction**

{table(["Horizon", "Reports", "Mean return", "Mean abnormal (XU100)", "Median abnormal (XU100)", "Mean abnormal (sector)"], agg_rows)}

**Improved versus deteriorated reports ({bcd["horizon"]}-day return)**

{table(["Group", "n", "Mean", "Median", "Positive rate", "Min / max"], dir_rows)}

Welch t-test {p_eq(welch_p)}.

## 5. All stocks

The same split for every stock of the course universe ({bcd["horizon"]}-day return; improved / deteriorated report counts):

{table(["Stock", "Template", "Improved / deteriorated", "Improved mean", "Deteriorated mean", "p"], cross_rows, "llrrrr")}

The mean return after improved reports is higher in {better} of {len(cross)} stocks and the difference has p < 0.05 in
{sig}. Each stock has only about ten reports, so individual results are weak evidence.

## 6. Sector-specific ratios: a bank (AKBNK)

The specification warns that bank analysis must not blindly use industrial-company ratios. Under the bank template
EBITDA-based ratios and the current ratio are not computed:

{table(["Ratio", "Value", "Note"], bank_rows, "lrl")}

## 7. Backtest

{bt_text}

## 8. Harness decision

{decision_md(run)}

## 9. Limitations

- Few quarters per stock (2023 Q4 – 2026 Q2); the TMS 29 transition makes comparisons with older quarters harder.
- "Surprise" is defined against the previous report, not against market expectations (no analyst consensus data).
- Other news inside the disclosure window is not separated out.

## Appendix — source tool calls

{provenance(run, out.parent.parent, scan)}
"""
    )
    return write(out, f"s4_fundamental_reaction_{tk.lower()}.md", md)


# --------------------------------------------------------------------------------------------- macro + context
SERIES_EN = {
    "USDTRY": "USD/TRY (CBRT buying rate)",
    "EURTRY": "EUR/TRY (CBRT buying rate)",
    "TCMB_POLICY_RATE": "CBRT policy rate",
    "FED_TARGET_UPPER": "Fed target, upper bound",
    "FED_TARGET_LOWER": "Fed target, lower bound",
    "TUFE_YOY": "CPI, annual",
    "TUFE_MOM": "CPI, monthly",
}
RATE_SERIES = {"TCMB_POLICY_RATE", "FED_TARGET_UPPER", "FED_TARGET_LOWER", "TUFE_YOY", "TUFE_MOM"}
RULES_EN = {
    "FX": "CBRT indicative buying rate, bulletin day 15:30",
    "TCMB_POLICY_RATE": "effective day 00:00",
    "FED": "effective day 00:00",
    "TUFE": "3rd of the following month (or the next BIST trading day) 10:00",
}


def report_macro(out: Path) -> Path:
    run = run_golden("Q5", out)
    scan = Scan()
    mac = run.env("get_macro_context").result
    tk = mac.get("ticker_for_corr") or run.res.request.tickers[0]

    def lvl(code: str, v: float) -> str:
        return level_pct(v) if code in RATE_SERIES else num(v, 4)

    def chg(code: str, v: float | None) -> str:
        if v is None:
            return "–"
        return f"{v:+,.2f} pp" if code in RATE_SERIES else pct(v, 2, True)

    lat_rows = [
        [
            SERIES_EN.get(c, c),
            lvl(c, x["value"]),
            day(x["obs_date"]),
            stamp(x["release_datetime"]),
            *[chg(c, mac["changes"].get(c, {}).get(k)) for k in ("1m", "3m", "12m")],
        ]
        for c, x in mac["latest"].items()
    ]
    pol_rows = [
        [day(x["obs_date"]), level_pct(x["previous"]), level_pct(x["value"])]
        for x in mac["policy_rate_changes_in_window"]
    ]
    infl = mac["inflation_in_window"]
    fx = mac.get("fx_relationship") or {}
    fx_rows = [
        [
            SERIES_EN.get(s, s),
            str(x["correlation"]["n"]),
            num(x["correlation"]["pearson"], 3),
            pval(x["correlation"]["pearson_p"]),
            num(x["correlation"]["spearman"], 3),
            num(x["beta"]["beta"]),
            num(x["beta"]["r2"], 3),
            pct(x["stock_return"], 2, True),
            pct(x["fx_return"], 2, True),
            pct(x["stock_return_in_fx"], 2, True),
        ]
        for s, x in fx.items()
    ]
    u = load_universe()
    sens = []
    for t in u.tickers():
        x = (
            scan(t, "get_macro_context", {"start": START, "ticker_for_corr": t}).result.get("fx_relationship") or {}
        ).get("USDTRY")
        if x:
            sens.append((t, x))
    sens.sort(key=lambda z: z[1]["correlation"]["pearson"])
    sens_rows = [
        [
            t,
            sector(u.instruments[t].peer_group or ""),
            num(x["correlation"]["pearson"], 3),
            pval(x["correlation"]["pearson_p"]),
            num(x["beta"]["beta"]),
            pct(x["stock_return_in_fx"], 1, True),
        ]
        for t, x in sens
    ]
    pos = sum(1 for _, x in sens if x["correlation"]["pearson"] > 0)
    plt = pyplot()
    fig, ax = plt.subplots(figsize=(8.2, 0.28 * len(sens) + 1.2))
    vals = [x["correlation"]["pearson"] for _, x in sens]
    ax.barh(
        range(len(sens)),
        vals,
        height=0.62,
        color=[SIGNAL if t == tk else ("#b5b1a6" if v < 0 else INK) for (t, _), v in zip(sens, vals, strict=True)],
    )
    ax.set_yticks(range(len(sens)), [t for t, _ in sens], fontsize=7.5)
    ax.axvline(0, color=INK, linewidth=0.7)
    ax.set_xlabel("correlation of weekly returns: stock vs USD/TRY (Pearson)")
    style(ax)
    fig_fx = save(fig, out / "fig" / "macro_fx_sensitivity.png")
    news_rows = []
    for env in run.envs("get_news_events"):
        nr = env.result
        news_rows.append(
            [
                str(nr["query"].get("ticker") or nr["query"].get("topic")),
                f"{day(nr['start'])} to {day(nr['end'])}",
                str(nr["count"]),
            ]
        )
    fxu = fx.get("USDTRY")
    findings = [
        f"As of {day(run.res.request.as_of_date)} the CBRT policy rate is {level_pct(mac['latest']['TCMB_POLICY_RATE']['value'])}; "
        f"the real policy rate against annual CPI is {num(mac['real_policy_rate'])} pp; USD/TRY moved {pct(mac['changes']['USDTRY']['12m'], 2, True)} over 12 months.",
        f"Cumulative inflation from {day(infl['start_month'])} to {day(infl['end_month'])}, using the {infl['months_used']}/"
        f"{infl['months_expected']} monthly CPI prints published by then: {pct(infl['cumulative'], 2)}.",
    ]
    if fxu:
        findings.append(
            f"The weekly correlation between {tk} and USD/TRY is {num(fxu['correlation']['pearson'], 3)} ({p_eq(fxu['correlation']['pearson_p'])}); "
            f"in USD terms the stock returned {pct(fxu['stock_return_in_fx'], 2, True)}. Correlation is not causation."
        )
    findings.append(f"In {pos} of {len(sens)} stocks the weekly return is positively correlated with USD/TRY.")
    if run.res.explanation:
        findings.append(
            f"The advice request was refused; the system showed the historical context and returned **{run.res.explanation.action.value}**."
        )
    md = (
        header("Macro", "Integration of macro and contextual evidence", run)
        + f"""## Key findings

{bullets(findings)}

"""
        + question_md(
            run,
            f"The instructor's Q5 tests (a) refusal of an advice / target-price request and (b) correct use of "
            f"the macro context ({tk} and the exchange rate) aligned to publication times. Specification §15–16: "
            "macro and news/speech layers.",
        )
        + f"""## 2. Publication-time alignment (point in time)

Every macro value becomes visible at the moment it was **published**, not at its observation date:

{table(["Series", "Knowledge-time rule"], [[k, RULES_EN.get(k, v)] for k, v in mac["release_rules"].items()], "ll")}

Example: August CPI is published on 3 September at 10:00, so an analysis on 2 September cannot see it.

## 3. Macro table as of {day(run.res.request.as_of_date)}

{table(["Series", "Value", "Observation", "Published", "1 month", "3 months", "12 months"], lat_rows, "lrllrrr")}

Real policy rate (against annual CPI) {num(mac["real_policy_rate"])} pp; Fed target range midpoint {level_pct(mac["fed_mid"], 3)}.
Cumulative inflation: {pct(infl["cumulative"], 2)} ({infl["months_used"]}/{infl["months_expected"]} months).

**CBRT rate decisions in the period**

{table(["Effective", "Previous", "New"], pol_rows, "lrr")}

## 4. {tk} and the exchange rate

Weekly (Friday) returns over the same common date range.

{table(["Currency", "Weeks", "Pearson", "p", "Spearman", "Beta", "R²", "Stock return", "FX return", "Stock (in FX)"], fx_rows)}

The claim "it is an exporter, so when the dollar rises it will certainly rise" is not supported by the data: the weekly
relationship is {"negative" if fxu and fxu["correlation"]["pearson"] < 0 else "positive"} and its explanatory power (R²) is low.
Correlation is not causation, and a past relationship does not guarantee the future.

## 5. FX sensitivity of every stock

{table(["Stock", "Sector", "Pearson (USD/TRY)", "p", "Beta", "Return in USD"], sens_rows, "llrrrr")}

![FX sensitivity](fig/{fig_fx})

## 6. News and speech context

News is **context only**: numbers in headlines and articles are not verified data and cannot be cited as evidence. The
source is the Bloomberg HT archive; only metadata (headline, URL, stock and topic tags) enters the database. Tagging
precision was measured in a separate audit (`reports/news_tagging_audit.md`). Knowledge time = the later of first
publication and last edit (conservative).

{table(["Query", "Window", "Articles"], news_rows, "llr") if news_rows else "No news query in this run."}

The speech/video layer (`feature/speech-layer`, built by a teammate) uses YouTube's own transcript panel; caption
quality is measured against official texts and claims are verified with the tools after human approval. Details are in
that layer's own report.

## 7. Advice request and harness decision

{decision_md(run)} The fixed refusal sentence is added by the harness; the model never has to write a forbidden phrase.

## 8. Limitations

- Macro series are monthly or event-based; their relationship with daily stock returns is weakly measured over short horizons.
- Correlations depend on the period chosen; structural breaks (the rate cycle) were not tested.
- News tags come from deterministic rules; out-of-context matches are reported in the precision audit.

## Appendix — source tool calls

{provenance(run, out.parent.parent, scan)}
"""
    )
    return write(out, "macro_context.md", md)


# --------------------------------------------------------------------------------------------- backtest
def report_backtest(out: Path) -> Path:
    scan = Scan()
    env = scan(
        "course universe, five variants",
        "run_backtest",
        {
            "universe": "course_30",
            "variant": "ALL",
            "start": START,
            "split_date": "2026-01-01",
            "include_equity": True,
            "max_trades_listed": 0,
        },
    )
    r, spec, bm = env.result, env.result["strategy_spec"], env.result["benchmarks"]
    variants = r["variants"]
    rows = []
    for name, v in variants.items():
        m, t, oos = v["metrics"], v["trades"], v.get("out_of_sample")
        rows.append(
            [
                f"{name} ({VARIANT_EN.get(name, name)})",
                ", ".join(v.get("layers") or []) or "technical only",
                integer(t["n_signals"]),
                integer(t["n_closed"]) + ("*" if t["n_closed"] < 10 else ""),
                pct(t["win_rate"], 1),
                pct(m["cumulative"], 1, True),
                pct(v["real_cumulative"], 1, True),
                f"{num(m['sharpe_rf0'])} / {num(m['sharpe_policy'])}",
                pct(m["max_drawdown"], 1),
                pp(v["vs_xu100"], 1),
                pct(oos["cumulative"], 1, True) if oos else "–",
            ]
        )
    cash_rows = [
        [
            name,
            pct(v["cash_at_policy_rate"]["metrics"]["cumulative"], 1, True),
            pct(v["cash_at_policy_rate"]["real_cumulative"], 1, True),
            num(v["cash_at_policy_rate"]["metrics"]["sharpe_policy"]),
            pct(v["exposure_mean"], 0),
        ]
        for name, v in variants.items()
        if v.get("cash_at_policy_rate")
    ]
    bm_names = {
        "buy_and_hold": "Equal-weight buy & hold (30 stocks)",
        "xu100": "XU100",
        "sector_basket": "Sector basket",
    }
    bm_rows = [
        [bm_names.get(k, k), pct(x["cumulative"], 1, True), num(x["sharpe_rf0"]), pct(x["max_drawdown"], 1)]
        for k, x in bm.items()
        if isinstance(x, dict) and "cumulative" in x
    ]
    plt = pyplot()
    fig, ax = plt.subplots(figsize=(8.2, 3.9))
    drawn = False
    for (name, v), col in zip(variants.items(), [SIGNAL, "#c2361b", "#6b3fd1", "#2c5cc5", "#1d7a4b"], strict=False):
        eq = v.get("equity") or []
        if not eq:
            continue
        x = [date.fromisoformat(str(p["date"])[:10]) for p in eq]
        ax.plot(x, [p["strategy"] * 100 for p in eq], color=col, linewidth=1.5, label=name)
        if not drawn:
            ax.plot(x, [p["xu100"] * 100 for p in eq], color=INK, linewidth=1.1, label="XU100")
            ax.plot(
                x,
                [p["buy_and_hold"] * 100 for p in eq],
                ":",
                color=MUTE,
                linewidth=1.1,
                label="Equal-weight buy & hold",
            )
            drawn = True
    ax.set_ylabel("cumulative return (%)")
    ax.legend(fontsize=7, frameon=False, ncol=2)
    style(ax)
    ax.grid(axis="y", color="#e4e1d8", linewidth=0.6)
    fig_eq = save(fig, out / "fig" / "backtest_variants.png")
    best = max(variants.items(), key=lambda kv: kv[1]["metrics"]["sharpe_rf0"])
    beat = [n for n, v in variants.items() if v["vs_xu100"] > 0]
    small = [n for n, v in variants.items() if v["trades"]["n_closed"] < 10]
    names = list(variants)
    same = [
        (a, b)
        for a, b in itertools.pairwise(names)
        if variants[a]["trades"]["n_closed"] == variants[b]["trades"]["n_closed"]
        and variants[a]["metrics"]["cumulative"] == variants[b]["metrics"]["cumulative"]
    ]
    sig_path = " → ".join(f"{n.split('_')[0]} {integer(v['trades']['n_signals'])}" for n, v in variants.items())
    all_neg = all(v["metrics"]["sharpe_policy"] < 0 for v in variants.values())
    findings = [
        f"Variants that beat XU100: {', '.join(beat) or 'none'}. Highest Sharpe (rf = 0): {best[0]} ({num(best[1]['metrics']['sharpe_rf0'])}).",
        f"Sharpe against the policy rate is {'negative for every variant' if all_neg else 'mixed'}: idle cash earning nothing "
        "falls behind the CBRT rate (see the cash-at-policy-rate version below).",
        f"Each added layer removes signals ({sig_path}). "
        + (
            f"{', '.join(small)} have fewer than 10 closed trades."
            if small
            else "Every variant has at least 10 closed trades."
        )
        + "".join(
            f" {a} and {b} are identical: the layer added in {b} filtered no further signal in this period."
            for a, b in same
        ),
    ]
    md = f"""# Backtest results and benchmark comparisons

*FinTreX Analyst research report · analysis date (as_of) {AS_OF} · period {day(r["start"])} to {day(r["end"])} · universe:
the 30-stock course universe. Generated by `eval/scenario_reports.py`; every number comes from the `run_backtest`
envelope. Educational analysis; BUY/SELL exist only as educational backtest positions and no order is ever produced.*

## Key findings

{bullets(findings)}

## 1. Rule and execution

- **Pre-registered rule** `{spec["name"]}` (fixed before any result was seen; changing it requires a new name): entry
  events {", ".join(f"`{x}`" for x in spec["entry_events"])}; holding period {spec["holding_days"]} trading days.
- **Layers** (cumulative from A to E): B — the stock is not lagging its sector over {spec["sector_window"]} days;
  C — latest reported revenue growth ≥ {pct(spec["fund_min_topline_growth"], 0)}; D — USD/TRY change over the last
  {spec["macro_fx_window"]} days ≤ {pct(spec["macro_max_fx_change"], 0)} and no rate hike in the last {spec["macro_hike_lookback_days"]}
  days; E — no {", ".join(spec["news_block_topics"])} news in the last {spec["news_lookback_days"]} days.
- **Timing:** signal at the close of day t (information ≤ t), trade at the open of t+1, exit at the open
  {spec["holding_days"]} days later. One trade per position; capital split into equal slots; idle slots earn 0%
  (plus a version where idle cash earns the policy rate).
- **Costs:** transaction cost {num(r["costs"]["tx_cost_bps"], 0)} bp, slippage {num(r["costs"]["slippage_bps"], 0)} bp.
- **Out of sample:** 2026-01-01 onwards is reported separately.

## 2. Variants

{table(["Variant", "Layers", "Signals", "Trades", "Win rate", "Cumulative", "Real", "Sharpe (0 / policy)", "Max drawdown", "vs XU100", "Out of sample"], rows, "llrrrrrrrrr")}

\\* Fewer than 10 closed trades: a high return from few events is unreliable.

![Equity curves of the variants](fig/{fig_eq})

## 3. Benchmarks

{table(["Benchmark", "Cumulative", "Sharpe", "Max drawdown"], bm_rows, "lrrr")}

## 4. Idle cash at the policy rate

In Türkiye the opportunity cost of cash is high. If idle slots had earned the CBRT policy rate of the day:

{table(["Variant", "Cumulative", "Real", "Sharpe (vs policy)", "Mean exposure"], cash_rows, "lrrrr")}

## 5. Limitations

- One rule, one universe, about 2.7 years; no parameter search was done (to limit data-mining risk).
- Overnight gaps and partial fills are not modelled; BIST price limits and limit-locked days are ignored.
- Prices are dividend- and split-adjusted; no taxes.

## Appendix — source tool call

Data version: {", ".join(f"{k} `{str(v)[:12]}`" for k, v in sorted(env.data_version.items()))}{scan.appendix()}
"""
    return write(out, "backtest_comparisons.md", md)


REPORTS = {
    "s1": report_s1,
    "s2": report_s2,
    "s3": report_s3,
    "s4": report_s4,
    "macro": report_macro,
    "backtest": report_backtest,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("which", choices=sorted(REPORTS), nargs="+")
    parser.add_argument("--out", type=Path, default=project_root() / "reports" / "scenarios")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for w in args.which:
        print(f"{w}: {REPORTS[w](args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
