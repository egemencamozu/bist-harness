"""Figures for the final technical report, drawn from the frozen evaluation reports (no number typed by hand).

    uv run --extra report python reports/final/build/make_figures.py

Writes PNGs to reports/final/build/fig/ and the numbers the report text uses to reports/final/build/data.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[3]
REP = ROOT / "reports"
OUT = Path(__file__).resolve().parent / "fig"
INK, SIGNAL, MUTE, LIGHT, PAPER = "#111110", "#ff4f1a", "#8a877e", "#e9e6dd", "#ffffff"
VIOLET, GREEN = "#6b3fd1", "#1d7a4b"


def load(rel: str) -> dict:
    return json.loads((REP / rel).read_text(encoding="utf-8"))


def style(ax) -> None:
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK)
        ax.spines[s].set_linewidth(0.8)
    ax.tick_params(colors=INK, labelsize=9)
    ax.set_axisbelow(True)


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)


def box(ax, x, y, w, h, title, sub="", fc=LIGHT, ec=INK, tc=INK, fs=10):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06", fc=fc, ec=ec, lw=1.1))
    ax.text(x + w / 2, y + h * (0.62 if sub else 0.5), title, ha="center", va="center", fontsize=fs, color=tc, weight="bold")
    if sub:
        ax.text(x + w / 2, y + h * 0.3, sub, ha="center", va="center", fontsize=7.6, color=tc)


def arrow(ax, a, b, color=INK, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=11, color=color, lw=1.1, linestyle=ls))


def architecture() -> None:
    fig, ax = plt.subplots(figsize=(10, 6.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6.2)
    ax.axis("off")
    # sources
    srcs = [("Prices", "price-scraper + yfinance"), ("KAP filings", "XBRL statements"), ("Macro", "CBRT, FRED, TurkStat"),
            ("News", "Bloomberg HT metadata"), ("Speech", "YouTube transcripts")]
    for i, (t, s) in enumerate(srcs):
        box(ax, 0.15 + i * 1.95, 5.25, 1.75, 0.7, t, s, fc=PAPER)
    box(ax, 0.15, 4.2, 9.55, 0.7, "Frozen snapshots + SQLite (data/db/bist.sqlite)",
        "sha256 manifests · knowledge-time column on every table · PITRepository: <= as_of filter + post-check")
    for i in range(5):
        arrow(ax, (1.02 + i * 1.95, 5.25), (1.02 + i * 1.95, 4.92))
    box(ax, 0.15, 3.05, 4.6, 0.9, "Analytics (pure Python)",
        "indicators · events · event study\nsector · weekday · fundamentals · macro")
    box(ax, 5.1, 3.05, 4.6, 0.9, "Backtest engine",
        "signal at close t → trade at open t+1\ncosts · XU100 / buy & hold / sector")
    box(ax, 0.15, 2.1, 9.55, 0.75, "15 MCP tools (thin layer)", "validate input → PIT read → analytics → ToolEnvelope (call_id, data_version, evidence candidates)")
    arrow(ax, (2.45, 4.2), (2.45, 3.92))
    arrow(ax, (7.4, 4.2), (7.4, 3.92))
    arrow(ax, (2.45, 3.15), (2.45, 2.87))
    arrow(ax, (7.4, 3.15), (7.4, 2.87))
    box(ax, 0.15, 0.85, 5.9, 0.95, "Stateful harness (17 states)",
        "permission map · as_of lock · evidence bundle\nrisk gate · validator · episodic memory · replay",
        fc=INK, ec=INK, tc=PAPER)
    box(ax, 6.4, 0.85, 3.3, 0.95, "Local LLM (Ollama)", "bist-analist · Qwen3.5-4B QLoRA\nunderstands · plans · explains", fc=PAPER, ec=VIOLET, tc=VIOLET)
    arrow(ax, (3.1, 2.1), (3.1, 1.82))
    arrow(ax, (6.06, 1.45), (6.38, 1.45), color=VIOLET, style="<|-|>")
    box(ax, 0.15, 0.0, 4.6, 0.6, "FinTreX Analyst web UI", "live 17-step view · evidence · review · replay", fc=PAPER)
    box(ax, 5.1, 0.0, 4.6, 0.6, "Human reviewer", "accept · modify · reject (with reason)", fc=PAPER, ec=SIGNAL, tc=SIGNAL)
    arrow(ax, (2.45, 0.85), (2.45, 0.62))
    arrow(ax, (4.77, 0.3), (5.08, 0.3), color=SIGNAL, style="<|-|>")
    save(fig, "architecture.png")


LABELS = {
    "START": "Start", "SELECT_UNIVERSE": "Select universe", "LOAD_MARKET_DATA": "Market data",
    "CHECK_DATA_QUALITY": "Data quality check", "CALCULATE_TECHNICALS": "Technicals",
    "RUN_SECTOR_RELATIVE_ANALYSIS": "Sector-relative", "RUN_PATTERN_AND_REVERSAL_ANALYSIS": "Patterns & reversals",
    "LOAD_FUNDAMENTALS": "Fundamentals (KAP)", "LOAD_MACRO_CONTEXT": "Macro context",
    "LOAD_NEWS_AND_SPEECH_CONTEXT": "News & speech", "BUILD_EVIDENCE": "Build evidence",
    "PREVIEW_STRATEGIES": "Preview strategies", "RUN_BACKTEST": "Backtest", "RISK_GATE": "Risk gate",
    "GENERATE_EXPLANATION": "Explain + validate", "HUMAN_REVIEW": "Human review", "LOG_AND_CLOSE": "Log and close",
}


def harness_flow() -> None:
    phases = [
        ("Preparation", ["START", "SELECT_UNIVERSE"]),
        ("Data", ["LOAD_MARKET_DATA", "CHECK_DATA_QUALITY*"]),
        ("Analysis", ["CALCULATE_TECHNICALS", "RUN_SECTOR_RELATIVE_ANALYSIS", "RUN_PATTERN_AND_REVERSAL_ANALYSIS",
                      "LOAD_FUNDAMENTALS", "LOAD_MACRO_CONTEXT", "LOAD_NEWS_AND_SPEECH_CONTEXT"]),
        ("Evidence & test", ["BUILD_EVIDENCE", "PREVIEW_STRATEGIES", "RUN_BACKTEST*"]),
        ("Control", ["RISK_GATE*"]),
        ("Explanation & review", ["GENERATE_EXPLANATION", "HUMAN_REVIEW", "LOG_AND_CLOSE"]),
    ]
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    x, n, w = 0.1, 0, 1.58
    for name, states in phases:
        ax.text(x + w / 2, 4.4, name, ha="center", fontsize=9, weight="bold", color=INK)
        for j, st in enumerate(states):
            n += 1
            mand = st.endswith("*")
            y = 3.85 - j * 0.62
            fc = SIGNAL if mand else (LIGHT if "LOAD" not in st and "RUN_" not in st and "CALC" not in st else PAPER)
            ax.add_patch(FancyBboxPatch((x, y - 0.24), w, 0.48, boxstyle="round,pad=0.01,rounding_size=0.05", fc=fc,
                                        ec=INK, lw=0.9))
            label = LABELS.get(st.rstrip("*"), st.rstrip("*").replace("_", " ").capitalize())
            ax.text(x + 0.07, y, f"{n:02d}", fontsize=7, color=PAPER if mand else MUTE, va="center")
            ax.text(x + 0.3, y, label, fontsize=7, ha="left", va="center", color=PAPER if mand else INK)
        x += w + 0.08
    ax.text(0.1, 0.05, "Orange = mandatory, never skipped. States that do not apply to a scenario are logged as "
            "SKIPPED_NOT_APPLICABLE with a reason.", fontsize=8, color=MUTE)
    save(fig, "harness_states.png")


def fine_tune(data: dict) -> None:
    ft, base = data["bakeoff"]["bist-analist"], data["bakeoff"]["qwen3.5:4b"]
    labels = ["First-attempt\nvalidator pass", "Completed without\nfallback", "Invented\nnumbers", "Forbidden\nphrases",
              "Same action as\nrule-based teacher"]
    keys = ["first_attempt_pass", "final_without_fallback", "questions_with_invented_numbers",
            "questions_with_forbidden_phrases", "teacher_agreement"]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    xs = range(len(keys))
    ax.bar([x - 0.19 for x in xs], [base[k] * 100 for k in keys], 0.36, color="#c9c5ba", label="qwen3.5:4b (base)")
    ax.bar([x + 0.19 for x in xs], [ft[k] * 100 for k in keys], 0.36, color=SIGNAL, label="bist-analist (fine-tuned)")
    for x, k in zip(xs, keys, strict=True):
        ax.text(x - 0.19, base[k] * 100 + 2, f"{base[k] * 100:.0f}%", ha="center", fontsize=8)
        ax.text(x + 0.19, ft[k] * 100 + 2, f"{ft[k] * 100:.0f}%", ha="center", fontsize=8, color=SIGNAL)
    ax.set_xticks(list(xs), labels, fontsize=8.5)
    ax.set_ylim(0, 112)
    ax.set_ylabel("share of 20 questions (%)")
    ax.legend(frameon=False, fontsize=8.5, loc="upper center", ncol=2)
    style(ax)
    ax.grid(axis="y", color="#ece9e1", lw=0.6)
    save(fig, "fine_tune.png")


def ablation(data: dict) -> None:
    lv = ["A", "B", "C", "D", "E"]
    names = ["A\nraw LLM", "B\n+ MCP tools", "C\n+ stateful\nharness", "D\n+ evidence\n+ risk gate", "E\n+ memory\n+ review"]
    ft, base = data["ablation"]["bist-analist"], data["ablation"]["qwen3.5:4b"]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    xs = range(5)
    ax.bar([x - 0.19 for x in xs], [base[k]["any_rule_violation"] * 100 for k in lv], 0.36, color="#c9c5ba", label="qwen3.5:4b (base)")
    ax.bar([x + 0.19 for x in xs], [ft[k]["any_rule_violation"] * 100 for k in lv], 0.36, color=SIGNAL, label="bist-analist (fine-tuned)")
    for x, k in zip(xs, lv, strict=True):
        ax.text(x - 0.19, base[k]["any_rule_violation"] * 100 + 1.5, f"{base[k]['any_rule_violation'] * 100:.0f}%", ha="center", fontsize=8)
        ax.text(x + 0.19, ft[k]["any_rule_violation"] * 100 + 1.5, f"{ft[k]['any_rule_violation'] * 100:.0f}%", ha="center", fontsize=8, color=SIGNAL)
    ax.set_xticks(list(xs), names, fontsize=8.5)
    ax.set_ylim(0, 80)
    ax.set_ylabel("answers with any rule violation (%)")
    ax.legend(frameon=False, fontsize=8.5)
    style(ax)
    ax.grid(axis="y", color="#ece9e1", lw=0.6)
    save(fig, "ablation.png")


def intent(data: dict) -> None:
    rows = [("Keyword rules", data["intent"]["rules"]), ("qwen3.5:4b", data["intent"]["llm:qwen3.5:4b"]),
            ("bist-analist", data["intent"]["llm:bist-analist"])]
    fig, ax = plt.subplots(figsize=(8, 2.4))
    for i, (name, s) in enumerate(rows):
        c, d, w = s["correct"] * 100, s["declined"] * 100, s["wrong"] * 100
        ax.barh(i, c, color=SIGNAL if name == "bist-analist" else INK, height=0.55)
        ax.barh(i, d, left=c, color="#c9c5ba", height=0.55)
        ax.barh(i, w, left=c + d, color="#c2361b", height=0.55)
        ax.text(c / 2, i, f"{c:.0f}% correct", ha="center", va="center", color=PAPER, fontsize=8)
        if d >= 8:
            ax.text(c + d / 2, i, f"{d:.0f}% declined", ha="center", va="center", color=INK, fontsize=8)
    ax.set_yticks(range(3), [r[0] for r in rows], fontsize=9)
    ax.set_xlim(0, 100)
    ax.set_xlabel("30 unseen free-text questions (robustness set v2)")
    style(ax)
    save(fig, "intent.png")


def scenario_findings() -> dict[str, list[str]]:
    """'Key findings' bullets of the generated scenario reports (English, every number from a tool envelope)."""
    out: dict[str, list[str]] = {}
    for path in sorted((REP / "scenarios").glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if "## Key findings" not in lines:
            continue
        i = lines.index("## Key findings") + 1
        bullets = []
        while i < len(lines) and not lines[i].startswith("## "):
            if lines[i].startswith("- "):
                bullets.append(lines[i][2:].replace("**", "").replace("`", ""))
            i += 1
        out[path.stem] = bullets
    return out


def main() -> None:
    data = {
        "bakeoff": {m: load(f"bakeoff_final/results_{f}.json")["summary"] for m, f in (("bist-analist", "bist-analist"), ("qwen3.5:4b", "qwen3.5_4b"))},
        "bakeoff_initial": {m: load(f"bakeoff/results_{f}.json")["summary"] for m, f in (("qwen2.5:7b", "qwen2.5_7b"), ("qwen3.5:9b", "qwen3.5_9b"), ("qwen3.5:4b", "qwen3.5_4b"))},
        "ablation": {m: load(f"ablation/ablation_{f}.json")["summary"] for m, f in (("bist-analist", "bist-analist"), ("qwen3.5:4b", "qwen3.5_4b"))},
        "intent": {k: v["summary"] for k, v in load("robustness/v2/intent_results.json").items()},
        "e2e": load("robustness/v2/e2e_bist-analist.json")["summary"],
        "golden": load("golden_final.json"),
        "dataset": json.loads((ROOT / "training" / "data" / "stats.json").read_text(encoding="utf-8")),
        "findings": scenario_findings(),
    }
    (Path(__file__).resolve().parent / "data.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    architecture()
    harness_flow()
    fine_tune(data)
    ablation(data)
    intent(data)
    print("figures in", OUT)


if __name__ == "__main__":
    main()
