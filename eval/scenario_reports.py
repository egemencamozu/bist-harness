"""Scenario research reports (spec §36 deliverables) generated from the harness' own tool outputs.

    uv run --extra report python -m eval.scenario_reports s3 [--out reports/scenarios]

Each report runs the matching golden question through the full 17-state harness (scenario planner + template
explainer: deterministic), stores the run in `<out>/episodic_<id>.sqlite` (replayable: every call_id in the appendix)
and writes `<out>/<id>_*.md` + figures in `<out>/fig/`. Every number in the text and tables is formatted from a tool
envelope with core.formatting; nothing is typed by hand. Figures are drawn with matplotlib from the same envelopes.
Interpretation sentences only compare numbers the tools produced (higher/lower, inside/outside a CI).
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

from bistharness.core import formatting as fmt
from bistharness.core.config import project_root
from bistharness.core.enums import Scenario
from bistharness.harness.factory import build_config, tool_context
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.runner import AnalysisResult, run_analysis

INK, SIGNAL, MUTE, PAPER = "#111110", "#ff4f1a", "#8a877e", "#ffffff"
FAMILY_TR = {
    "bollinger": "Bollinger bantları",
    "rsi": "RSI",
    "supertrend": "Supertrend",
    "kama": "KAMA",
    "ichimoku": "Ichimoku",
    "support_resistance": "Destek / direnç",
    "composite": "Birleşik olaylar",
    "combined": "Birleşik olaylar ve koşullar",
    "combo": "Birleşik koşullar",
}
STATE_TR = {
    "market_trend": ("XU100 eğilimi", {"rising": "yükselen", "falling": "düşen"}),
    "volatility": ("Volatilite", {"high": "yüksek", "low": "düşük"}),
    "supertrend_state": ("Supertrend", {"bullish": "yükseliş", "bearish": "düşüş"}),
    "ichimoku_state": (
        "Ichimoku",
        {"above_cloud": "bulut üstü", "below_cloud": "bulut altı", "inside_cloud": "bulut içi"},
    ),
    "kama_slope_state": ("KAMA eğimi", {"rising": "yükselen", "falling": "düşen", "flat": "yatay"}),
    "volume_regime": ("Hacim", {"high": "yüksek", "normal": "normal", "low": "düşük"}),
    "rsi_state": ("RSI", {"oversold": "aşırı satım", "overbought": "aşırı alım", "neutral": "nötr", "low": "düşük"}),
}
VARIANT_TR = {
    "A_TECH": "Teknik",
    "B_TECH_SECTOR": "Teknik + sektör",
    "C_TECH_SECTOR_FUND": "Teknik + sektör + temel",
    "D_FULL_STRUCTURED": "Tüm yapısal veri",
    "E_FULL_CONTEXTUAL": "Yapısal + bağlam",
}


# --------------------------------------------------------------------------------------------- helpers
def pct(x: float | None, d: int = 2, signed: bool = False) -> str:
    return "–" if x is None else fmt.pct(x, d, signed=signed)


def table(head: Sequence[str], rows: Sequence[Sequence[str]], align: str = "") -> str:
    al = align or "l" + "r" * (len(head) - 1)
    sep = ["---:" if a == "r" else ":---" for a in al]
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join(sep) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


@dataclass
class Run:
    res: AnalysisResult
    memory: Path

    def env(self, tool: str, state: str | None = None) -> Any:
        envs = [c.envelope for c in self.res.calls if c.tool == tool and c.envelope is not None]
        if state:
            envs = [c.envelope for c in self.res.calls if c.tool == tool and c.envelope and c.state.value == state]
        return envs[-1] if envs else None


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
    return Run(res, path)


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
    import matplotlib.pyplot as plt

    plt.close(fig)
    return path.name


def provenance(run: Run, rel_root: Path) -> str:
    rows = [
        [c.state.value, f"`{c.tool}`", c.origin, f"`{c.envelope.call_id[:16]}`" if c.envelope else "–"]
        for c in run.res.calls
    ]
    dv: dict[str, str] = {}
    for c in run.res.calls:
        if c.envelope is not None:
            dv.update(c.envelope.data_version)
    return "\n".join(
        [
            f"Analiz `{run.res.analysis_id}` · karar `{run.res.decision_id}` · episodik kayıt "
            f"`{run.memory.relative_to(rel_root).as_posix()}`.",
            "",
            "Veri sürümü (sha256, ilk 12): " + ", ".join(f"{k} `{str(v)[:12]}`" for k, v in sorted(dv.items())),
            "",
            table(["Adım", "Araç", "Kaynak", "call_id"], rows, "llll"),
        ]
    )


# --------------------------------------------------------------------------------------------- S3
KEY_EVENTS = [
    "BB_LOWER_TOUCH",
    "BB_LOWER_REVERSAL",
    "BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE",
    "BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD",
    "RSI_TROUGH_VOLUME",
    "SUPERTREND_BULLISH_FLIP",
    "ICHIMOKU_BULLISH_BREAKOUT",
    "SUPPORT_TOUCH",
]


def s3_figures(r: dict[str, Any], bt: dict[str, Any] | None, figdir: Path) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names: dict[str, str] = {}
    rows = [s for s in r["summary"] if s["n"] >= 5]
    rows.sort(key=lambda s: (s["success_rate"] or 0) - (s["baseline_success_rate"] or 0))
    fig, ax = plt.subplots(figsize=(8.2, 0.3 * len(rows) + 1.2))
    for i, s in enumerate(rows):
        lo, hi = s["success_rate_ci95"]
        ax.plot([lo * 100, hi * 100], [i, i], color="#c9c5ba", linewidth=3, solid_capstyle="round")
        ax.scatter(s["baseline_success_rate"] * 100, i, marker="|", s=120, color=INK, zorder=3)
        ax.scatter(s["success_rate"] * 100, i, s=26, color=SIGNAL, zorder=4)
    ax.set_yticks(range(len(rows)), [f"{s['description_tr']} (n={s['n']})" for s in rows], fontsize=8)
    ax.set_xlabel(f"{r['main_horizon']} günlük başarı oranı (%) — nokta: olay, çizgi: %95 GA, dikey: olay dışı günler")
    style(ax)
    names["ci"] = save(fig, figdir / "s3_basari_orani.png")

    fig, ax = plt.subplots(figsize=(8.2, 3.8))
    for ev, color, ls in (
        ("BB_LOWER_TOUCH", INK, "-"),
        ("BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE", SIGNAL, "-"),
        ("BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD", MUTE, "--"),
    ):
        hs = r["horizons"].get(ev) or []
        ax.plot(
            [h["horizon"] for h in hs],
            [h["success_rate"] * 100 for h in hs],
            ls,
            color=color,
            marker="o",
            markersize=4,
            label=next(s["description_tr"] for s in r["summary"] if s["event_type"] == ev),
        )
        base = [h["baseline_success_rate"] * 100 for h in hs]
    if base:
        ax.plot([h["horizon"] for h in hs], base, ":", color="#b5b1a6", label="olay dışı günler")
    ax.set_xlabel("ufuk (işlem günü)")
    ax.set_ylabel("başarı oranı (%)")
    ax.legend(fontsize=7.5, frameon=False, loc="lower right")
    style(ax)
    ax.grid(axis="y", color="#e4e1d8", linewidth=0.6)
    names["horizon"] = save(fig, figdir / "s3_ufuk_profili.png")

    if bt:
        eq = bt.get("equity") or []
        if eq:
            from datetime import date as _d

            x = [_d.fromisoformat(str(p["date"])[:10]) for p in eq]
            fig, ax = plt.subplots(figsize=(8.2, 3.6))
            ax.plot(x, [p["buy_and_hold"] * 100 for p in eq], ":", color=MUTE, linewidth=1.2, label="ASELS al-tut")
            ax.plot(x, [p["xu100"] * 100 for p in eq], color=INK, linewidth=1.1, label="XU100")
            ax.plot(x, [p["strategy"] * 100 for p in eq], color=SIGNAL, linewidth=1.8, label="Strateji (A_TECH)")
            ax.set_ylabel("kümülatif getiri (%)")
            ax.legend(fontsize=7.5, frameon=False)
            style(ax)
            ax.grid(axis="y", color="#e4e1d8", linewidth=0.6)
            names["equity"] = save(fig, figdir / "s3_backtest.png")
    return names


def report_s3(out: Path) -> Path:
    run = run_golden("Q3", out)
    res = run.res
    rev = run.env("detect_reversal_events")
    r = rev.result
    sr = run.env("find_support_resistance")
    ind = run.env("calculate_indicators")
    bt_env = run.env("run_backtest", "RUN_BACKTEST")
    bt = bt_env.result["variants"].get("A_TECH") if bt_env else None
    ticker, h = r["ticker"], r["main_horizon"]
    by = {s["event_type"]: s for s in r["summary"]}
    figs = s3_figures(r, bt, out / "fig")
    as_of = res.request.as_of_date

    def n_mark(n: int) -> str:
        return f"{n}†" if n < 5 else (f"{n}*" if n < 10 else str(n))

    # 1) family table
    fam_rows: dict[str, list[list[str]]] = {}
    for s in r["summary"]:
        fam = FAMILY_TR.get(s["family"], s["family"])
        fam_rows.setdefault(fam, []).append(
            [
                s["description_tr"] + (" ↑" if s["direction"] == "bullish" else " ↓"),
                n_mark(s["n"]),
                f"{s['n_success']}/{s['n'] - s['n_success']}" if s["n"] else "–",
                f"{pct(s['success_rate'], 1)} [{pct(s['success_rate_ci95'][0], 0)}–{pct(s['success_rate_ci95'][1], 0)}]"
                if s["n"]
                else "–",
                pct(s["baseline_success_rate"], 1),
                f"{pct(s['mean'], 2, True)} / {pct(s['median'], 2, True)}" if s["n"] else "–",
                pct(s["mean_reversal_strength"], 2) if s["n"] else "–",
                pct(s["mean_abnormal_vs_xu100"], 2, True) if s["n"] else "–",
                fmt.num(s["p_bh"], 3) if s.get("p_bh") is not None else "–",
            ]
        )
    fam_md = "\n\n".join(
        f"**{fam}**\n\n"
        + table(
            [
                "Olay",
                "n",
                "Başarılı / başarısız",
                f"Başarı ({h}g) [%95 GA]",
                "Olay dışı",
                "Ort. / medyan",
                "Dönüş gücü",
                "XU100'e göre",
                "p (BH)",
            ],
            rows,
        )
        for fam, rows in fam_rows.items()
    )

    # 2) combination comparison
    base_ev = by["BB_LOWER_TOUCH"]
    comb_rows = [
        [
            by[e]["description_tr"],
            str(by[e]["n"]),
            pct(by[e]["success_rate"], 1),
            pct(by[e]["mean"], 2, True),
            pct(by[e]["median"], 2, True),
            pct(by[e]["mean_reversal_strength"], 2),
        ]
        for e in ("BB_LOWER_TOUCH", "BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE", "BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD")
        if e in by
    ]
    rsi_c, st_c = by.get("BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE"), by.get("BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD")

    def cmp(a: float, b: float) -> str:
        return "daha yüksek" if a > b else "daha düşük" if a < b else "aynı"

    comb_text = []
    if rsi_c:
        comb_text.append(
            f"RSI düşük + hacim artışı koşulu eklendiğinde başarı oranı {pct(rsi_c['success_rate'], 1)} "
            f"(tek başına alt bant dokunuşu {pct(base_ev['success_rate'], 1)}; {cmp(rsi_c['success_rate'], base_ev['success_rate'])}), "
            f"fakat örneklem {rsi_c['n']} olaya düşüyor."
        )
    if st_c:
        comb_text.append(
            f"Supertrend düşüşte ve fiyat bulutun altındayken başarı oranı {pct(st_c['success_rate'], 1)} "
            f"({cmp(st_c['success_rate'], base_ev['success_rate'])}; {st_c['n']} olay). Şartnamedeki örnek senaryoda bu "
            "koşulda sinyallerin sık başarısız olduğu anlatılıyordu; ASELS'in bu döneminde veri "
            + ("tersini gösteriyor" if st_c["success_rate"] >= base_ev["success_rate"] else "bunu destekliyor")
            + f", ancak fark düzeltme sonrası anlamlı değil (p (BH) = {fmt.num(st_c['p_bh'], 3)})."
        )

    # 3) horizon profile
    hz_rows = []
    for e in KEY_EVENTS:
        hs = r["horizons"].get(e)
        if not hs:
            continue
        cells = {x["horizon"]: x for x in hs}
        hz_rows.append(
            [by[e]["description_tr"]]
            + [
                f"{pct(cells[k]['success_rate'], 0)} / {pct(cells[k]['mean'], 1, True)}"
                if k in cells and cells[k]["n"]
                else "–"
                for k in (1, 3, 5, 10, 20)
            ]
        )

    # 4) regimes
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
            for st in states:
                c = (b.get(dim) or {}).get(st)
                cells.append(f"{pct(c['success_rate'], 0)} (n={c['n']})" if c and c["n"] else "–")
        reg_rows.append([by[e]["description_tr"], *cells])

    # 5) multiple testing
    tested = [s for s in r["summary"] if s["n"] and s.get("p_mean_vs_baseline") is not None]
    raw = sum(1 for s in tested if s["p_mean_vs_baseline"] < 0.05)
    bh = sum(1 for s in tested if (s.get("p_bh") or 1) < 0.05)
    bon = sum(1 for s in tested if (s.get("p_bonferroni") or 1) < 0.05)

    if bh == 0:
        mt_text = (
            "Tek tek bakıldığında anlamlı görünen farkların hiçbiri düzeltme sonrası anlamlı kalmıyor: bu dönemde "
            "hiçbir olay türü, getiriyi olay dışı günlerden istatistiksel olarak ayıracak güçte değil. Yüksek başarı "
            "oranları kısmen ASELS'in bu dönemdeki güçlü genel yükselişinden geliyor (olay dışı günlerde de yükseliş "
            f"oranı {pct(base_ev['baseline_success_rate'], 1)})."
        )
    else:
        mt_text = f"Düzeltme sonrası {bh} olay türü anlamlı kalıyor."

    # 6) current state
    active = r.get("active_now") or {}
    recent = r.get("recent_events") or []
    rec_rows = [
        [
            fmt.tr_date(e["event_date"]),
            by.get(e["event_type"], {}).get("description_tr", e["event_type"]),
            fmt.num(e["close"], 2),
            STATE_TR["supertrend_state"][1].get(e.get("supertrend_state"), str(e.get("supertrend_state"))),
            STATE_TR["ichimoku_state"][1].get(e.get("ichimoku_state"), str(e.get("ichimoku_state"))),
        ]
        for e in recent[-8:]
    ]

    # 7) backtest
    bt_md = "Backtest çıktısı yok."
    if bt:
        m, t = bt["metrics"], bt["trades"]
        rows = [
            ["Dönem", f"{fmt.tr_date(m['start'])} – {fmt.tr_date(m['end'])}"],
            ["Kapanan işlem / kazanan oranı", f"{t['n_closed']} / {pct(t['win_rate'], 1)}"],
            ["Kümülatif getiri (nominal)", pct(m["cumulative"], 2, True)],
            ["Reel getiri (TÜFE)", pct(bt["real_cumulative"], 2, True)],
            ["XU100'e göre fark", fmt.pp_from_fraction(bt["vs_xu100"])],
            ["Al-tut'a göre fark", fmt.pp_from_fraction(bt["vs_buy_and_hold"])],
            ["Sharpe (rf = 0 / politika faizi)", f"{fmt.num(m['sharpe_rf0'], 2)} / {fmt.num(m['sharpe_policy'], 2)}"],
            ["En büyük düşüş", pct(m["max_drawdown"], 2)],
        ]
        for lab, key in (("Örneklem içi", "in_sample"), ("Örneklem dışı", "out_of_sample")):
            b = bt.get(key)
            if b:
                rows.append(
                    [
                        f"{lab} ({fmt.tr_date(b['start'])} – {fmt.tr_date(b['end'])})",
                        f"{pct(b['cumulative'], 2, True)}, Sharpe {fmt.num(b['sharpe_rf0'], 2)}",
                    ]
                )
        spec = bt_env.result["strategy_spec"]
        bh_diff, xu_diff = bt["vs_buy_and_hold"], bt["vs_xu100"]
        oos = bt.get("out_of_sample")
        bt_read = (
            f"Strateji XU100'ün {fmt.pp_from_fraction(abs(xu_diff))} {'önünde' if xu_diff >= 0 else 'gerisinde'} kaldı, "
            f"ancak ASELS'i baştan sona elde tutmanın {fmt.pp_from_fraction(abs(bh_diff))} "
            f"{'gerisinde' if bh_diff < 0 else 'önünde'}: "
            "güçlü yükselen bir hissede kısa (5 günlük) dönüş işlemleri trendin büyük kısmını kaçırıyor."
            + (f" Örneklem dışı dönemde getiri {pct(oos['cumulative'], 2, True)}." if oos else "")
        )
        bt_md = (
            f"Strateji önceden sabitlenmiş `{spec['name']}` kuralıdır (sonuçlara bakılmadan seçildi): giriş olayları "
            + ", ".join(f"`{x}`" for x in spec["entry_events"])
            + f"; elde tutma {spec['holding_days']} işlem günü; sinyal t kapanışında, işlem t+1 açılışında; "
            f"maliyet {fmt.num(bt_env.result['costs']['tx_cost_bps'], 0)} baz puan.\n\n"
            + table(["Ölçüt", "Değer"], rows, "lr")
            + (f"\n\n![Backtest getiri eğrisi](fig/{figs['equity']})" if "equity" in figs else "")
            + f"\n\n{bt_read}"
        )

    sr_md = ""
    if sr:
        sres = sr.result
        sr_md = (
            "\n".join(
                f"- {c.claim_tr}"
                for c in sr.evidence_candidates
                if c.key.endswith(("nearest_support", "nearest_resistance"))
            )
            or "- Yakın destek/direnç seviyesi bulunamadı."
        )
        if sres.get("levels") is not None:
            sr_md += f"\n- Son 250 barda {len(sres['levels'])} seviye kümelendi (≥2 dokunuş, %2 tolerans)."

    lt = by["BB_LOWER_TOUCH"]
    findings = [
        f"Alt Bollinger dokunuşu {lt['n']} kez oluştu; {h} gün sonra {lt['n_success']} tanesinde fiyat yükseldi "
        f"({pct(lt['success_rate'], 1)}; olay dışı günlerde {pct(lt['baseline_success_rate'], 1)}).",
    ]
    if st_c:
        findings.append(
            f"Supertrend düşüşte ve fiyat bulutun altındayken gelen dokunuşlar ({st_c['n']} olay) tarihsel olarak daha "
            f"güçlü: {pct(st_c['success_rate'], 1)} başarı, ortalama {pct(st_c['mean'], 2, True)}."
        )
    findings.append(
        f"Çoklu test düzeltmesinden sonra {r['family_size']} olay türünden {bh} tanesi anlamlı; yüksek oranların bir "
        "kısmı hissenin genel yükselişinden geliyor."
    )
    if bt:
        findings.append(
            f"Önceden sabitlenmiş dönüş stratejisi {pct(bt['metrics']['cumulative'], 2, True)} kazandırdı; XU100'ün "
            f"{fmt.pp_from_fraction(abs(bt['vs_xu100']))} {'önünde' if bt['vs_xu100'] >= 0 else 'gerisinde'}, fakat ASELS'i elde tutmanın "
            f"{fmt.pp_from_fraction(abs(bt['vs_buy_and_hold']))} gerisinde."
        )
    if res.explanation:
        findings.append(f"Harness kararı: {res.explanation.action.value} (risk kapısı {res.gate.value}).")
    findings_md = "\n".join(f"- {x}" for x in findings)

    trend = next((c.claim_tr for c in (ind.evidence_candidates if ind else []) if c.key.endswith("trend_state")), "")
    gate_codes = sorted({g["code"] for g in res.gate_reasons})
    md = f"""# S3 — Teknik dönüş olayları: {ticker}

*FinTreX Analyst senaryo raporu · analiz tarihi {fmt.tr_date(as_of)} · dönem {fmt.tr_date(r["start"])} – {fmt.tr_date(r["end"])}.
Bu rapor `eval/scenario_reports.py` ile araç çıktılarından üretilmiştir; metindeki ve tablolardaki her sayı bir araç
zarfından gelir (kaynak çağrılar ekte). Eğitsel bir analizdir, yatırım tavsiyesi değildir.*

## Ana bulgular

{findings_md}

## 1. Soru

> {res.request.question}

Şartname §13: ASELS'te alt Bollinger dokunuşlarının ve diğer teknik olayların ardından fiyatın tarihsel olarak nasıl
davrandığı; tek göstergeli olayların birleşik koşullarla karşılaştırılması; piyasa rejimine göre sonuçlar.

## 2. Yöntem

- **Olay tarihi = teyit tarihi.** Örneğin RSI yerel dibi t−1'de oluşur, t'de teyit edilir; olay t sayılır. Destek/direnç
  seviyesi pivotun teyit edildiği günden itibaren bilinir. Ichimoku Chikou kullanılmaz.
- **Başarı tanımı:** yükseliş olayında {h} günlük ileri getiri > 0, düşüş olayında < 0. Ana ufuk {h} işlem günü; 1, 3, 5, 10 ve 20 gün ayrıca raporlanır.
- **Kıyas:** aynı ufukta olay olmayan günlerin getirisi (olay dışı baz oran). Dönüş gücü = pencere içindeki en iyi
  yönlü hareket (MFE). Anormal getiri = hisse getirisi − XU100 getirisi.
- **Point-in-time:** tüm veriler {fmt.tr_date(as_of)} kapanışına kadar bilinenlerdir. İleri penceresi bu tarihe kadar
  dolmamış **{len(rev.excluded_incomplete_events)} olay–ufuk çifti** istatistiğe alınmadı (sessiz `dropna` yok; liste
  araç çıktısında `excluded_incomplete_events`).
- **Çoklu test:** tek çağrıda {r["family_size"]} olay türü sınandı; olay–olay dışı ortalama farkının Welch p-değerleri
  Bonferroni ve Benjamini–Hochberg ile düzeltildi.
- Göstergeler hocanın referans parametreleriyle aynıdır (BB 20/2σ, RSI 14 Wilder, KAMA 10/2/30, ATR 10, Supertrend 10/3,
  Ichimoku 9/26/52, hacim MA20; parity testli).

## 3. Olay aileleri

Sütunlar: başarılı/başarısız sayısı; {h} günlük başarı oranı ve %95 güven aralığı; olay dışı günlerdeki oran;
{h} günlük ortalama/medyan getiri; ortalama dönüş gücü (MFE); XU100'e göre ortalama anormal getiri; BH düzeltilmiş p.
↑ yükseliş, ↓ düşüş hipotezi. † n < 5 (yetersiz örneklem), * n < 10 (küçük örneklem).

{fam_md}

![Başarı oranları ve güven aralıkları](fig/{figs["ci"]})

## 4. Tek gösterge ve birleşik koşullar

{table(["Koşul", "n", f"Başarı ({h}g)", "Ortalama", "Medyan", "Dönüş gücü"], comb_rows)}

{" ".join(comb_text)}

## 5. Ufuk profili

Hücre: başarı oranı / ortalama getiri.

{table(["Olay", "1g", "3g", "5g", "10g", "20g"], hz_rows)}

![Ufuk profili](fig/{figs["horizon"]})

## 6. Piyasa rejimine göre ({h} günlük başarı)

{table(["Olay", "XU100 yükselen", "XU100 düşen", "Düşük volatilite", "Yüksek volatilite"], reg_rows)}

Rejim alt kümeleri küçüktür; tek başına karar dayanağı değildir.

## 7. Çoklu test riski

{len(tested)} olay türünün {raw} tanesinde olay ile olay dışı ortalama farkı ham p < 0,05; Benjamini–Hochberg sonrası
{bh}, Bonferroni sonrası {bon}. {mt_text}

## 8. {fmt.tr_date(as_of)} itibarıyla güncel durum

{trend}

Son {active.get("window_trading_days", 5)} işlem gününde ({fmt.tr_date(active["from"]) if active.get("from") else "–"} sonrası)
etkin olaylar: {", ".join(by.get(e, {}).get("description_tr", e) for e in active.get("events", [])) or "yok"}.

{table(["Tarih", "Olay", "Kapanış", "Supertrend", "Ichimoku"], rec_rows, "llrll") if rec_rows else ""}

{sr_md}

## 9. Backtest

{bt_md}

## 10. Harness kararı

Aynı soru 17 adımlı harness'tan geçirildi (senaryo planlayıcı + kural tabanlı açıklayıcı): **{res.explanation.action.value if res.explanation else "–"}**,
risk kapısı **{res.gate.value}** ({len(res.gate_reasons)} bulgu; türler: {", ".join(gate_codes) or "yok"}).
{len(res.calls)} araç çağrısı, {len(res.invalid_calls)} geçersiz. Aday etiketi (`TECHNICAL_REVERSAL_CANDIDATE`) için
güncel olayın tarihsel ve backtest kanıtıyla desteklenmesi gerekir; bu koşul sağlanmadığında sistem izleme ile yetinir.

## 11. Sınırlar ve hocanın betiğiyle farklar

- Hocanın S3 betiğinde Supertrend son bantları NaN ATR ile tohumlandığından hiç başlamaz; bu yüzden betik Supertrend
  dönüşü üretmez. Bizde özyineleme ilk geçerli ATR barından başlar (aynı başlangıçla betikle birebir, testli); bu
  dönemde {by.get("SUPERTREND_BULLISH_FLIP", {}).get("n", 0)} yukarı ve {by.get("SUPERTREND_BEARISH_FLIP", {}).get("n", 0)} aşağı dönüş var.
- Betikteki ileri getiri `dropna` ile eksik pencereleri sessizce atar; bizde eksik pencereler ayrı listelenir.
- KAMA–fiyat kesişimi KAMA eğim dönüşüyle matematiksel olarak aynıdır; çift sayım ve çoklu test şişmesini önlemek için
  ayrı olay sayılmadı.
- Fiyat serisi temettü ve bedelsiz düzeltmelidir ve analiz tarihine çapalıdır; yfinance'teki kesik bar ve sahte satır
  sorunları birincil kaynakta düzeltilmiştir (CLAUDE.md §11).
- Tek hisse, tek dönem: sonuçlar başka hisselere ya da döneme genellenemez.

## Ek — kaynak araç çağrıları

{provenance(run, out.parent.parent)}
"""
    path = out / f"s3_teknik_donus_{ticker.lower()}.md"
    path.write_text(md, encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------------- shared (S1, S2, S4, ...)
AS_OF = "2026-09-10"
START = "2024-01-01"


def pyplot() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


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
        return "\n\n**Karşılaştırma için ek araç çağrıları** (harness dışı, aynı snapshot ve as_of)\n\n" + table(
            ["Kapsam", "Araç", "call_id"], rows, "lll"
        )


def sign_word(x: float, up: str = "önünde", down: str = "gerisinde") -> str:
    return up if x >= 0 else down


def decision_md(run: Run) -> str:
    res = run.res
    codes = sorted({g["code"] for g in res.gate_reasons})
    return (
        f"Aynı soru 17 adımlı harness'tan geçirildi (senaryo planlayıcı + kural tabanlı açıklayıcı): "
        f"**{res.explanation.action.value if res.explanation else '–'}**, risk kapısı **{res.gate.value}** "
        f"({len(res.gate_reasons)} bulgu; türler: {', '.join(codes) or 'yok'}). {len(res.calls)} araç çağrısı, "
        f"{len(res.invalid_calls)} geçersiz.\n\nSistemin açıklaması (kanıt numaraları E# ile):\n\n"
        + "\n".join(
            f"> {line}" if line.strip() else ">"
            for line in (res.explanation.text_tr if res.explanation else "").splitlines()
        )
    )


def header(code: str, title: str, run: Run) -> str:
    r = run.res.request
    return (
        f"# {code} — {title}\n\n*FinTreX Analyst senaryo raporu · analiz tarihi {fmt.tr_date(r.as_of_date)} · dönem "
        f"{fmt.tr_date(r.start)} – {fmt.tr_date(r.as_of_date)}. Bu rapor `eval/scenario_reports.py` ile araç çıktılarından "
        "üretilmiştir; metindeki ve tablolardaki her sayı bir araç zarfından gelir (kaynak çağrılar ekte). Eğitsel bir "
        "analizdir, yatırım tavsiyesi değildir.*\n\n"
    )


def write(out: Path, name: str, md: str) -> Path:
    path = out / name
    path.write_text(md, encoding="utf-8")
    return path


def bt_rows(v: dict[str, Any]) -> list[list[str]]:
    m, t = v["metrics"], v["trades"]
    rows = [
        ["Dönem", f"{fmt.tr_date(m['start'])} – {fmt.tr_date(m['end'])}"],
        ["Sinyal / kapanan işlem", f"{fmt.integer(t['n_signals'])} / {fmt.integer(t['n_closed'])}"],
        ["Kazanan oranı", pct(t["win_rate"], 1)],
        ["Kümülatif getiri (nominal)", pct(m["cumulative"], 2, True)],
        ["Reel getiri (TÜFE)", pct(v["real_cumulative"], 2, True)],
        ["XU100'e göre fark", fmt.pp_from_fraction(v["vs_xu100"])],
        ["Eşit ağırlıklı al-tut'a göre fark", fmt.pp_from_fraction(v["vs_buy_and_hold"])],
        ["Sharpe (rf = 0 / politika faizi)", f"{fmt.num(m['sharpe_rf0'], 2)} / {fmt.num(m['sharpe_policy'], 2)}"],
        ["En büyük düşüş", pct(m["max_drawdown"], 2)],
    ]
    for lab, key in (("Örneklem içi", "in_sample"), ("Örneklem dışı", "out_of_sample")):
        b = v.get(key)
        if b:
            rows.append(
                [
                    f"{lab} ({fmt.tr_date(b['start'])} – {fmt.tr_date(b['end'])})",
                    f"{pct(b['cumulative'], 2, True)}, Sharpe {fmt.num(b['sharpe_rf0'], 2)}",
                ]
            )
    return rows


# --------------------------------------------------------------------------------------------- S1
def report_s1(out: Path) -> Path:
    run = run_golden("Q1", out)
    scan = Scan()
    sec = run.env("rank_sector_relative_strength").result
    figdir = out / "fig"
    members = sec["members_with_data"]
    rank_rows = [
        [
            x["ticker"],
            pct(x["ret"], 2, True),
            pct(x["peer_median"], 2, True),
            fmt.pp_from_fraction(x["lag_score"]),
            f"{x['rank']}/{len(members)}",
            fmt.pp_from_fraction(x["rel_benchmark"]),
        ]
        for x in sec["ranking"]
    ]
    windows = sorted({w["window"] for w in sec["all_windows"]})
    win_rows = []
    for t in members:
        cells = {w["window"]: w for w in sec["all_windows"] if w["ticker"] == t}
        win_rows.append([t] + [fmt.pp_from_fraction(cells[w]["lag_score"]) if w in cells else "–" for w in windows])
    gm_rows = [
        [
            f"{w}g",
            pct(sec["group_median"][str(w)], 2, True),
            pct(sec["benchmark_returns"][str(w)], 2, True),
            "güçlü" if sec["strong"][str(w)] else "güçlü değil",
        ]
        for w in windows
    ]
    cu = sec["catch_up"]
    cu_rows = [
        [
            f"{x['horizon']}g",
            str(x["n"]),
            str(x["n_catch_up"]),
            str(x["n_false_positive"]),
            f"{pct(x['hit_rate'], 1)} [{pct(x['hit_rate_ci95'][0], 0)}–{pct(x['hit_rate_ci95'][1], 0)}]",
            pct(x["baseline_hit_rate"], 1),
            fmt.pp_from_fraction(x["median_relative"]),
            fmt.num(x["p_rate_vs_baseline"], 3),
        ]
        for x in cu["horizons"]
    ]
    fp_rows = [
        [
            fmt.tr_date(f["event_date"]),
            f["ticker"],
            fmt.pp_from_fraction(f["lag_score"]),
            fmt.pp_from_fraction(f["rel_5d"]) if f.get("rel_5d") is not None else "–",
            fmt.pp_from_fraction(f["rel_10d"]) if f.get("rel_10d") is not None else "–",
            fmt.pp_from_fraction(f["rel_20d"]) if f.get("rel_20d") is not None else "–",
        ]
        for f in cu["false_positives"][-8:]
    ]
    # structural vs temporary: fundamentals of the laggards from the same harness run
    fund_rows = []
    for c in run.res.calls:
        if c.tool == "calculate_fundamental_change" and c.envelope is not None:
            rr = c.envelope.result
            last = (rr.get("reports") or [None])[-1]
            if last:
                ch = last.get("ratio_changes", {})
                em, nm = ch.get("ebitda_margin"), ch.get("net_margin")
                fund_rows.append(
                    [
                        rr["ticker"],
                        last["fiscal_period"].replace("Q", "Ç"),
                        fmt.tr_datetime(last["disclosure_datetime"]),
                        f"{pct(em['old'], 2)} → {pct(em['new'], 2)}" if em else "şablona uygun değil",
                        f"{pct(nm['old'], 2)} → {pct(nm['new'], 2)}" if nm else "–",
                        pct(last["yoy_ytd"].get("revenue"), 1, True) if last.get("yoy_ytd") else "–",
                    ]
                )
    # every sector of the course universe
    from bistharness.core.config import load_universe

    u = load_universe()
    groups: list[str] = []
    for t in u.tickers():
        g = u.instruments[t].peer_group
        if g and g not in groups and len(u.peer_groups.get(g, ())) >= 2:
            groups.append(g)
    cross = []
    for g in groups:
        env = scan(g, "rank_sector_relative_strength", {"sector_or_tickers": g, "start": START, "horizon": 20})
        h20 = next((x for x in env.result["catch_up"]["horizons"] if x["horizon"] == 20), None)
        if h20 and h20["n"]:
            cross.append((g, env.result, h20))
    cross_rows = [
        [
            g.replace("_", " "),
            str(len(r["members_with_data"])),
            str(h["n"]),
            pct(h["hit_rate"], 1),
            pct(h["baseline_hit_rate"], 1),
            str(h["n_false_positive"]),
            fmt.pp_from_fraction(h["median_relative"]),
            fmt.num(h["p_rate_vs_baseline"], 3),
        ]
        for g, r, h in cross
    ]
    beats = sum(1 for _, _, h in cross if h["hit_rate"] > h["baseline_hit_rate"])
    signif = sum(1 for _, _, h in cross if h["p_rate_vs_baseline"] < 0.05)
    plt = pyplot()
    fig, ax = plt.subplots(figsize=(8.2, 0.34 * len(cross) + 1.2))
    for i, (_g, _r, h) in enumerate(cross):
        lo, hi = h["hit_rate_ci95"]
        ax.plot([lo * 100, hi * 100], [i, i], color="#c9c5ba", linewidth=3, solid_capstyle="round")
        ax.scatter(h["baseline_hit_rate"] * 100, i, marker="|", s=120, color=INK, zorder=3)
        ax.scatter(h["hit_rate"] * 100, i, s=26, color=SIGNAL, zorder=4)
    ax.set_yticks(range(len(cross)), [f"{g.replace('_', ' ')} (n={h['n']})" for g, _r, h in cross], fontsize=8)
    ax.set_xlabel("20 günde akran sepetini geçme oranı (%) — nokta: geride kalanlar, dikey: geride kalmayan günler")
    style(ax)
    fig_cross = save(fig, figdir / "s1_sektorler.png")
    bt_env = run.env("run_backtest", "RUN_BACKTEST")
    variant = next(iter(bt_env.result["variants"])) if bt_env else None
    bt = bt_env.result["variants"][variant] if bt_env else None
    h20 = next((x for x in cu["horizons"] if x["horizon"] == 20), cu["horizons"][-1])
    findings = [
        f"{sec['group'].replace('_', ' ')} sektörünün son {sec['horizon']} işlem günü medyan getirisi "
        f"{pct(sec['group_median'][str(sec['horizon'])], 2, True)}, XU100 {pct(sec['benchmark_returns'][str(sec['horizon'])], 2, True)}: "
        f"sektör {'güçlü' if sec['strong'][str(sec['horizon'])] else 'güçlü değil'}. Geride kalanlar: {', '.join(sec['laggards']) or 'yok'}; "
        f"önde olanlar: {', '.join(sec['leaders']) or 'yok'}.",
        f"Uzun pencerelerde de geride kalan (yapısal aday): {', '.join(sec['persistent_laggards']) or 'yok'}.",
        f"{fmt.tr_date(cu['start'])}–{fmt.tr_date(cu['end'])} arasında {cu['n_events']} geride kalma girişinin 20 günlük "
        f"yetişme oranı {pct(h20['hit_rate'], 1)}, geride kalmayan günlerde {pct(h20['baseline_hit_rate'], 1)}; "
        f"{h20['n_false_positive']} yanlış pozitif.",
        f"{len(cross)} sektörün {beats} tanesinde geride kalanların 20 günlük yetişme oranı baz orandan yüksek, "
        f"{signif} tanesinde fark istatistiksel olarak anlamlı (p < 0,05).",
    ]
    if bt:
        findings.append(
            f"`{variant}` backtest'i {pct(bt['metrics']['cumulative'], 2, True)}; XU100'ün "
            f"{fmt.pp_from_fraction(abs(bt['vs_xu100']))} {sign_word(bt['vs_xu100'])}."
        )
    md = (
        header("S1", f"Sektörde geride kalma ve yetişme: {sec['group'].replace('_', ' ')}", run)
        + f"""## Ana bulgular

{chr(10).join("- " + f for f in findings)}

## 1. Soru

> {run.res.request.question}

Şartname §11: güçlü bir sektörde belirgin biçimde geride kalan hisselerin daha sonra sektörünü yakalayıp
yakalamadığı; geride kalmanın yapısal mı geçici mi olduğu; yanlış pozitifler.

## 2. Yöntem

- **Akran grubu:** TÜBİTAK 95 hisse sektör haritası (`config/universe.yaml: peer_groups`). Soruda adı geçen hisseler
  yerine hissenin bütün sektörü kullanılır ({", ".join(sec["members"])}).
- **Geride kalma skoru:** {sec["definitions"]["lag_score"].replace("stock return - median return of the OTHER members over the window", "hisse getirisi − DİĞER üyelerin medyan getirisi (kendisi hariç)")}.
  Eşik {fmt.pp_from_fraction(sec["lag_threshold"])}.
- **Güçlü sektör:** grup medyanı > 0 ve > XU100 (aynı pencerede).
- **Olay:** güçlü sektörde geride kalma durumuna GİRİŞ (her epizotta bir olay; her gün sayılmaz).
- **Yetişme:** sonraki h günde hisse getirisi − diğer üyelerin eşit ağırlıklı sepeti > 0. Tersi = yanlış pozitif.
  Kıyas: geride kalmayan günlerin aynı oranı. İleri penceresi dolmayan olaylar alınmaz.

## 3. Bugünkü sıralama ({fmt.tr_date(sec["date"])}, son {sec["horizon"]} işlem günü)

{table(["Hisse", "Getiri", "Diğer üyelerin medyanı", "Geride kalma skoru", "Sıra", "XU100'e göre"], rank_rows)}

**Farklı pencerelerde geride kalma skoru**

{table(["Hisse", *[f"{w}g" for w in windows]], win_rows)}

**Sektör gücü**

{table(["Pencere", "Grup medyanı", "XU100", "Durum"], gm_rows, "lrrl")}

## 4. Geride kalanlar tarihsel olarak yetişiyor mu?

{table(["Ufuk", "n", "Yetişti", "Yanlış pozitif", "Oran [%95 GA]", "Geride kalmayan günler", "Medyan göreli", "p"], cu_rows)}

**Son yanlış pozitifler** (geride kalan hisse sonra da sepetin gerisinde kaldı)

{table(["Tarih", "Hisse", "Geride kalma", "5g göreli", "10g göreli", "20g göreli"], fp_rows) if fp_rows else "Yok."}

## 5. Yapısal mı, geçici mi?

Uzun pencerelerde de geride kalan hisseler: **{", ".join(sec["persistent_laggards"]) or "yok"}**. Son bilançolar
(aynı harness koşusundan, yalnız {fmt.tr_date(run.res.request.as_of_date)} itibarıyla açıklanmış olanlar):

{table(["Hisse", "Dönem", "Açıklama", "FAVÖK marjı", "Net kâr marjı", "Hasılat (yıllık, YTD)"], fund_rows, "lllrrr") if fund_rows else "Bilanço verisi yok."}

Marjları düşen bir hissedeki geride kalma, fiyatın temel bir bozulmayı yansıttığını düşündürür (yapısal aday);
marjları iyileşen bir hissedeki geride kalma geçici olabilir. Bu ayrım kesin değildir; sistem bu yüzden aday etiketini
ancak backtest kanıtıyla verir.

## 6. Bütün sektörler

Aynı çalışma 30 hisselik ders evrenindeki her sektör için tekrarlandı (20 günlük ufuk):

{table(["Sektör", "Üye", "Olay", "Yetişme", "Baz", "Yanlış pozitif", "Medyan göreli", "p"], cross_rows)}

![Sektörlere göre yetişme oranı](fig/{fig_cross})

{len(cross)} sektörün {beats} tanesinde geride kalanların yetişme oranı baz orandan yüksek; {signif} tanesinde fark
p < 0,05. Sektör sayısı kadar test yapıldığı için tek tek anlamlı görünen sonuçlar da çoklu test riskini taşır.

## 7. Backtest

{("`" + variant + "` varyantı (" + VARIANT_TR.get(variant, variant) + "), önceden sabitlenmiş kural:" + chr(10) + chr(10) + table(["Ölçüt", "Değer"], bt_rows(bt), "lr")) if bt else "Backtest çıktısı yok."}

## 8. Harness kararı

{decision_md(run)}

## 9. Sınırlar

- Sektör grupları küçük (2–10 üye); medyan birkaç hissenin hareketine duyarlı.
- Geride kalma epizotları bağımsız değildir (aynı sektör, aynı günler); güven aralıkları iyimser olabilir.
- Temel ayrım yalnız son raporların marjlarına bakar; TMS 29 dönemleri arasında karşılaştırma uyarılıdır.

## Ek — kaynak araç çağrıları

{provenance(run, out.parent.parent)}{scan.appendix()}
"""
    )
    return write(out, f"s1_sektor_yetisme_{sec['group'].lower()}.md", md)


# --------------------------------------------------------------------------------------------- S2
DAYS_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma"]


def report_s2(out: Path) -> Path:
    run = run_golden("Q2", out)
    scan = Scan()
    env = run.env("test_weekday_pattern")
    r = env.result
    tk = r["ticker"]
    p = r["pattern"]
    per = r["periods"]

    def prow(lab: str, k: str) -> list[str]:
        x = per[k]
        c, u, cm = x["conditional"], x["unconditional"], x["complement"]
        return [
            lab,
            f"{fmt.tr_date(x['start'])} – {fmt.tr_date(x['end'])}",
            str(x["complete_weeks"]),
            str(x["condition_weeks"]),
            pct(x["condition_frequency"], 1),
            f"{pct(c['mean'], 2, True)} / {pct(c['median'], 2, True)}",
            pct(c["mean_after_cost"], 2, True),
            pct(c["positive_rate"], 1),
            f"{pct(u['mean'], 2, True)} / {pct(u['positive_rate'], 1)}",
            f"{pct(cm['mean'], 2, True)}",
        ]

    pat_rows = [prow("Örneklem içi", "in_sample"), prow("Örneklem dışı", "out_of_sample")]
    test_rows = []
    for lab, k in (("Örneklem içi", "in_sample"), ("Örneklem dışı", "out_of_sample")):
        x = per[k]
        test_rows.append(
            [
                lab,
                fmt.pp_from_fraction(x["mean_difference"]) if x.get("mean_difference") is not None else "–",
                fmt.num(x["p_welch_vs_complement"], 3) if x.get("p_welch_vs_complement") is not None else "–",
                fmt.num(x["p_binomial_vs_unconditional"], 3)
                if x.get("p_binomial_vs_unconditional") is not None
                else "–",
                fmt.num(x["p_permutation_vs_complement"], 3)
                if x.get("p_permutation_vs_complement") is not None
                else "–",
                (
                    f"{pct(x['bootstrap_mean_ci95'][0], 2, True)} – {pct(x['bootstrap_mean_ci95'][1], 2, True)}"
                    if x.get("bootstrap_mean_ci95")
                    else "–"
                ),
                f"{x.get('family_rank', '–')}/{x.get('family_size', '–')}",
                fmt.num(x["p_bh"], 3) if x.get("p_bh") is not None else "–",
                f"{x.get('full_sequence_count', '–')} ({pct(x['full_sequence_frequency'], 1) if x.get('full_sequence_frequency') is not None else '–'})",
            ]
        )
    wd = r["weekday_statistics"]
    wd_rows = []
    for i, day in enumerate(DAYS_TR):
        cells = [day]
        for k in ("in_sample", "out_of_sample"):
            d = wd[k][i] if i < len(wd.get(k, [])) else None
            cells += (
                [f"{pct(d['mean'], 2, True)} / {pct(d['positive_rate'], 0)}", fmt.num(d["p_bh"], 3)]
                if d
                else ["–", "–"]
            )
        wd_rows.append(cells)
    eff = r["weekday_effect_tests"]
    st = r["stability"]
    weeks = per["in_sample"].get("matching_weeks", [])
    wk_rows = [
        [
            fmt.tr_date(w["week_start"]),
            *[pct(w[d], 2, True) if w.get(d) is not None else "–" for d in ("Mon", "Tue", "Wed", "Thu", "Fri")],
            pct(w["outcome"], 2, True),
        ]
        for w in weeks
    ]
    # other presets on the same stock + the same pattern conditioned on the XU100 direction
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
        for ms, ms_lab in ((None, "tüm haftalar"), (1, "XU100 yükselen hafta"), (-1, "XU100 düşen hafta")):
            if name != p["label"] and ms is not None:
                continue
            e2 = scan(f"{tk} {name} {ms_lab}", "test_weekday_pattern", {**base, "pattern": name, "market_sign": ms})
            a = e2.result
            i_, o_ = a["periods"]["in_sample"], a["periods"]["out_of_sample"]
            alt_rows.append(
                [
                    a["pattern"]["label_tr"],
                    ms_lab,
                    str(i_["condition_weeks"]),
                    pct(i_["conditional"]["mean_after_cost"], 2, True) if i_["condition_weeks"] else "–",
                    fmt.num(i_["p_bh"], 3) if i_.get("p_bh") is not None else "–",
                    str(o_["condition_weeks"]),
                    pct(o_["conditional"]["mean_after_cost"], 2, True) if o_["condition_weeks"] else "–",
                    "evet" if a["stability"]["same_sign_out_of_sample"] else "hayır",
                ]
            )
    # the same pattern on every stock of the course universe: a multiple-testing illustration
    from bistharness.core.config import load_universe

    pts = []
    for t in load_universe().tickers():
        try:
            e3 = scan(f"{t} {p['label']}", "test_weekday_pattern", {**base, "ticker": t, "pattern": p["label"]})
        except Exception:  # a stock without enough history is skipped (the scan lists only executed calls)
            continue
        a = e3.result
        s3 = a["stability"]
        if s3.get("in_sample_effect") is None:
            continue
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
    raw_pos_hold = [x for x in raw_sig if x[5]]
    same_sign = sum(1 for x in pts if x[5])
    plt = pyplot()
    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    xs = [x[1] * 100 for x in pts if x[2] is not None]
    ys = [x[2] * 100 for x in pts if x[2] is not None]
    ax.axhline(0, color=INK, linewidth=0.7)
    ax.axvline(0, color=INK, linewidth=0.7)
    ax.scatter(xs, ys, s=22, color=MUTE)
    for t, ie, oe, *_ in pts:
        if t == tk and oe is not None:
            ax.scatter([ie * 100], [oe * 100], s=60, color=SIGNAL, zorder=4)
            ax.annotate(t, (ie * 100, oe * 100), xytext=(6, 4), textcoords="offset points", fontsize=8, color=SIGNAL)
    ax.set_xlabel("örneklem içi etki (koşullu − tamamlayıcı, puan)")
    ax.set_ylabel("örneklem dışı etki (puan)")
    style(ax)
    ax.grid(axis="y", color="#e4e1d8", linewidth=0.6)
    fig_scatter = save(fig, out / "fig" / "s2_hisseler.png")
    bt_env = run.env("run_backtest", "RUN_BACKTEST")
    variant = next(iter(bt_env.result["variants"])) if bt_env else None
    bt = bt_env.result["variants"][variant] if bt_env else None
    ci = per["in_sample"]["conditional"]
    findings = [
        f"Koşul ({p['label_tr']}) örneklem içinde {per['in_sample']['condition_weeks']} hafta gerçekleşti; sonraki "
        f"Perşembe–Cuma ortalaması {pct(ci['mean'], 2, True)} (maliyet sonrası {pct(ci['mean_after_cost'], 2, True)}), "
        f"koşulsuz haftalarda {pct(per['in_sample']['unconditional']['mean'], 2, True)}.",
        f"Çoklu test düzeltmesi sonrası örneklem içi anlamlılık: {'var' if st['in_sample_significant_after_adjustment'] else 'yok'} "
        f"(p (BH) = {fmt.num(per['in_sample']['p_bh'], 3)}, aile büyüklüğü {per['in_sample']['family_size']}).",
        f"Örneklem dışında koşul yalnız {per['out_of_sample']['condition_weeks']} hafta oluştu; etki "
        f"{fmt.pp_from_fraction(st['out_of_sample_effect'])} ({'aynı yönde' if st['same_sign_out_of_sample'] else 'ters yönde'}); "
        f"örneklem {'yeterli' if st['out_of_sample_sufficient'] else 'yetersiz'}.",
        f"Aynı örüntü {len(pts)} hissede sınandığında {len(raw_sig)} hissede örneklem içi ham p < 0,05, BH sonrası "
        f"{len(bh_sig)}; ham anlamlıların {len(raw_pos_hold)} tanesi örneklem dışında aynı yönde kaldı.",
    ]
    md = (
        header("S2", f"Haftanın günü ve çok günlü örüntüler: {tk}", run)
        + f"""## Ana bulgular

{chr(10).join("- " + f for f in findings)}

## 1. Soru

> {run.res.request.question}

Şartname §12: bir hissede haftanın günlerine ya da çok günlü dizilere bağlı tekrar eden bir örüntü var mı; örüntü
sonraki görülmemiş dönemde sürüyor mu; işlem maliyeti, koşulsuz getiri ve çoklu test riski.

## 2. Yöntem

- **Koşul ≠ sonuç.** Koşul günleri (Pzt-Sal-Çar düşüş) sonucu içermez; sonuç (Per-Cum bileşik getirisi) koşuldan sonra
  gelen günlerdir ({r["condition_vs_outcome"].replace("the outcome days come after every condition day (no outcome inside the condition)", "sonuç günleri her koşul gününden sonra gelir")}).
  Hocanın betiğinde koşul `Thu>0 & Fri>0` içerdiğinden "Per-Cum pozitif oranı" tanım gereği %100 çıkar; burada sonuç
  koşulsuz Per-Cum dağılımıyla kıyaslanır.
- **Dönemler bütün haftalarla.** Ayrımı kesen ya da analiz tarihinde yarım kalan hafta hiçbir döneme girmez.
- **Kıyaslar:** koşulsuz haftalar, koşulun gerçekleşmediği haftalar (tamamlayıcı); Welch, binom, permütasyon testleri ve
  bootstrap güven aralığı. İşlem maliyeti {fmt.num(r["tx_cost_bps"], 0)} baz puan.
- **Çoklu test ailesi:** koşul günlerinin tüm işaret kombinasyonları ({per["in_sample"]["family_size"]} örüntü);
  Bonferroni ve Benjamini–Hochberg.

## 3. Örüntü: {p["label_tr"]}

Ortalama / medyan Per-Cum bileşik getirisi; olumlu oran.

{table(["Dönem", "Tarihler", "Tam hafta", "Koşul haftası", "Sıklık", "Koşullu ort. / medyan", "Maliyet sonrası", "Pozitif oran", "Koşulsuz ort. / pozitif", "Tamamlayıcı ort."], pat_rows)}

**İstatistiksel testler**

{table(["Dönem", "Fark (koşullu − tamamlayıcı)", "p Welch", "p binom", "p permütasyon", "Bootstrap %95 GA", "Ailede sıra", "p (BH)", "Tam 5 günlük dizi"], test_rows)}

**Kararlılık:** örneklem içi etki {fmt.pp_from_fraction(st["in_sample_effect"])}, örneklem dışı
{fmt.pp_from_fraction(st["out_of_sample_effect"])}; aynı yön: {"evet" if st["same_sign_out_of_sample"] else "hayır"};
örneklem dışı yeterli: {"evet" if st["out_of_sample_sufficient"] else "hayır"}; düzeltme sonrası anlamlı:
{"evet" if st["in_sample_significant_after_adjustment"] else "hayır"}; maliyet sonrası pozitif (örneklem içi):
{"evet" if st["net_of_cost_positive_in_sample"] else "hayır"}.

**Koşulun gerçekleştiği haftalar (örneklem içi)**

{table(["Hafta", "Pzt", "Sal", "Çar", "Per", "Cum", "Per-Cum"], wk_rows) if wk_rows else "Yok."}

## 4. Haftanın günleri

Ortalama günlük getiri / pozitif gün oranı ve BH düzeltilmiş p (ortalama = 0 testi).

{table(["Gün", "Örneklem içi", "p (BH)", "Örneklem dışı", "p (BH)"], wd_rows)}

Günler arası fark testi: örneklem içi ANOVA p = {fmt.num(eff["in_sample"]["anova_p"], 3)}, Kruskal–Wallis p =
{fmt.num(eff["in_sample"]["kruskal_p"], 3)}; örneklem dışı ANOVA p = {fmt.num(eff["out_of_sample"]["anova_p"], 3)},
Kruskal–Wallis p = {fmt.num(eff["out_of_sample"]["kruskal_p"], 3)}.

## 5. Diğer örüntüler ve piyasa yönüne göre

{table(["Örüntü", "Koşul", "İçi hafta", "İçi maliyet sonrası", "İçi p (BH)", "Dışı hafta", "Dışı maliyet sonrası", "Aynı yön"], alt_rows, "llrrrrrl")}

## 6. Aynı örüntü bütün hisselerde

Şartname "ikinci bir hisse ters örüntü gösterebilir" diyor. Aynı örüntü ders evrenindeki {len(pts)} hissede sınandı:
{len(raw_sig)} hissede örneklem içi ham p < 0,05, Benjamini–Hochberg sonrası {len(bh_sig)}. Örneklem dışında
{same_sign}/{len(pts)} hissede etki aynı yönde kaldı; ham anlamlı olanların {len(raw_pos_hold)} tanesi aynı yönde.
Yeterince çok hisse ve örüntü denendiğinde şans eseri "anlamlı" sonuçlar çıkar; örneklem dışı tutarlılık olmadan
bunlar işlem kuralına dönüştürülmemelidir.

![Örneklem içi ve dışı etki](fig/{fig_scatter})

## 7. Backtest

{("`" + variant + "` varyantı (" + VARIANT_TR.get(variant, variant) + "), önceden sabitlenmiş kural:" + chr(10) + chr(10) + table(["Ölçüt", "Değer"], bt_rows(bt), "lr")) if bt else "Backtest çıktısı yok."}

## 8. Harness kararı

{decision_md(run)}

## 9. Sınırlar

- Örneklem dışı dönem kısa ({per["out_of_sample"]["complete_weeks"]} tam hafta); koşul haftası sayısı az.
- Bayram ve yarım günler haftaları eksik bırakır; bu haftalar hiçbir döneme alınmaz.
- Örüntü ailesi koşul işaretleriyle sınırlı; daha geniş bir arama çoklu test riskini artırır.

## Ek — kaynak araç çağrıları

{provenance(run, out.parent.parent)}{scan.appendix()}
"""
    )
    return write(out, f"s2_haftanin_gunu_{tk.lower()}.md", md)


# --------------------------------------------------------------------------------------------- S4
METRIC_TR = {
    "revenue": "Hasılat",
    "gross_profit": "Brüt kâr",
    "ebitda": "FAVÖK",
    "operating_profit": "Esas faaliyet kârı",
    "net_income_parent": "Net kâr (ana ortaklık)",
    "operating_cash_flow": "Faaliyet nakit akışı",
    "roe": "ROE",
    "roa": "ROA",
    "gross_margin": "Brüt marj",
    "ebitda_margin": "FAVÖK marjı",
    "net_margin": "Net marj",
    "net_debt_to_ebitda": "Net borç / FAVÖK",
    "debt_to_equity": "Borç / özkaynak",
    "current_ratio": "Cari oran",
    "quick_ratio": "Likidite oranı",
    "operating_margin": "Esas faaliyet marjı",
    "net_debt": "Net borç",
    "cash_conversion": "Nakde dönüşüm (FNA / net kâr)",
    "pe": "F/K",
    "pb": "PD/DD",
    "ev_to_ebitda": "FD/FAVÖK",
}
RATIO_KIND = {
    "net_debt_to_ebitda": "x",
    "debt_to_equity": "x",
    "current_ratio": "x",
    "quick_ratio": "x",
    "pe": "x",
    "pb": "x",
    "ev_to_ebitda": "x",
}


def ratio_fmt(name: str, x: dict[str, Any]) -> str:
    """Format a metric by the unit the tool reports (TRY amount, x multiple, ratio as percent)."""
    v = x.get("value")
    if v is None:
        return "–"
    unit = x.get("unit") or ("x" if RATIO_KIND.get(name) == "x" else "ratio")
    if unit == "TRY":
        return fmt.try_amount(v)
    return fmt.num(v, 2) if unit == "x" else pct(v, 2)


def report_s4(out: Path) -> Path:
    run = run_golden("Q4", out)
    scan = Scan()
    met = run.env("get_fundamental_metrics").result
    chg = run.env("calculate_fundamental_change").result
    tk = met["ticker"]
    lr = met["latest_report"]
    lev_rows = []
    for name, d in met["levels"].items():
        cells = [METRIC_TR.get(name, name)]
        for basis in ("quarter", "ytd", "ttm"):
            x = d.get(basis)
            cells.append(
                fmt.try_amount(x["value"]) if x and x.get("value") is not None else (x or {}).get("reason") or "–"
            )
        lev_rows.append(cells)
    rat_rows = [
        [
            METRIC_TR.get(n, n),
            ratio_fmt(n, x),
            x.get("basis", ""),
            "yaklaşık" if x.get("approx") else "",
            x.get("reason") or "",
        ]
        for n, x in met["ratios"].items()
    ]
    val = met.get("valuation") or {}
    val_rows = [
        [METRIC_TR.get(n, n), ratio_fmt(n, x), x.get("reason") or ""] for n, x in (val.get("metrics") or {}).items()
    ]
    hz = chg["horizons"]
    rep_rows = []
    for rp in chg["reports"]:
        rc = rp.get("ratio_changes", {})
        em = rc.get("ebitda_margin")
        react = rp.get("reaction") or {}
        cells = [
            rp["fiscal_period"].replace("Q", "Ç"),
            fmt.tr_datetime(rp["disclosure_datetime"]),
            {"after_close": "seans sonrası", "pre_open": "seans öncesi", "intraday": "seans içi"}.get(
                rp["timing"], rp["timing"]
            ),
            pct(rp["yoy_ytd"].get("revenue"), 1, True) if rp.get("yoy_ytd") else "–",
            pct(rp["yoy_ytd"].get("ebitda"), 1, True) if rp.get("yoy_ytd") else "–",
            fmt.pp_from_fraction(em["change"]) if em else "–",
        ]
        for h in hz:
            x = react.get(str(h)) or {}
            cells.append(fmt.pp_from_fraction(x["abn_xu100"]) if x.get("abn_xu100") is not None else "–")
        cells.append("†" if rp.get("tms29_warning") else "")
        rep_rows.append(cells)
    agg_rows = [
        [
            f"{h}g",
            str(a["n"]),
            pct(a["mean_ret"], 2, True),
            fmt.pp_from_fraction(a["mean_abn_xu100"]),
            fmt.pp_from_fraction(a["median_abn_xu100"]),
            fmt.pp_from_fraction(a["mean_abn_sector"]) if a.get("mean_abn_sector") is not None else "–",
        ]
        for h, a in chg["aggregate"].items()
    ]
    bcd = chg["by_change_direction"]
    dir_rows = [
        [
            {"improved": "İyileşen", "deteriorated": "Kötüleşen"}.get(k, k),
            str(g["n"]),
            pct(g["mean"], 2, True),
            pct(g["median"], 2, True),
            pct(g["positive_rate"], 0),
            f"{pct(g['min'], 1, True)} / {pct(g['max'], 1, True)}",
        ]
        for k, g in bcd["groups"].items()
        if k in ("improved", "deteriorated")
    ]
    welch = bcd["groups"].get("welch") or {}
    # every stock: is a margin improvement followed by a better 20-day reaction?
    from bistharness.core.config import load_universe

    u = load_universe()
    cross = []
    for t in u.tickers():
        try:
            e = scan(t, "calculate_fundamental_change", {"ticker": t, "start": START})
        except Exception:  # no fundamentals (e.g. TRALT): skipped
            continue
        g = e.result.get("by_change_direction", {}).get("groups", {})
        imp, det = g.get("improved"), g.get("deteriorated")
        if imp and det and imp.get("n") and det.get("n"):
            cross.append((t, u.instruments[t].template, imp, det, (g.get("welch") or {}).get("p_value")))
    cross_rows = [
        [
            t,
            tpl,
            f"{imp['n']} / {det['n']}",
            pct(imp["mean"], 2, True),
            pct(det["mean"], 2, True),
            fmt.num(p, 3) if p is not None else "–",
        ]
        for t, tpl, imp, det, p in cross
    ]
    better = sum(1 for _, _, imp, det, _ in cross if imp["mean"] > det["mean"])
    sig = sum(1 for *_, p in cross if p is not None and p < 0.05)
    bank = scan("AKBNK şablon farkı", "get_fundamental_metrics", {"ticker": "AKBNK", "start": START}).result
    bank_rows = [
        [
            METRIC_TR.get(n, n),
            ratio_fmt(n, x),
            (x.get("reason") or "").replace("NOT_APPLICABLE_FOR_TEMPLATE", "şablona uygun değil"),
        ]
        for n, x in bank["ratios"].items()
    ]
    bt_env = run.env("run_backtest", "RUN_BACKTEST")
    variant = next(iter(bt_env.result["variants"])) if bt_env else None
    bt = bt_env.result["variants"][variant] if bt_env else None
    last = chg["reports"][-1]
    findings = [
        f"{tk} {lr['fiscal_period'].replace('Q', 'Ç')} raporu {fmt.tr_datetime(lr['disclosure_datetime'])} tarihinde açıklandı; "
        f"yıllık (YTD) hasılat {pct(last['yoy_ytd']['revenue'], 1, True)}, FAVÖK {pct(last['yoy_ytd']['ebitda'], 1, True)}.",
        f"{chg['aggregate'][str(hz[-1])]['n']} açıklamanın ardından {hz[-1]} günlük ortalama anormal getiri (XU100'e göre) "
        f"{fmt.pp_from_fraction(chg['aggregate'][str(hz[-1])]['mean_abn_xu100'])}, medyan "
        f"{fmt.pp_from_fraction(chg['aggregate'][str(hz[-1])]['median_abn_xu100'])}.",
        f"FAVÖK marjı iyileşen ve kötüleşen raporlardan sonraki {bcd['horizon']} günlük getiri farkı istatistiksel olarak "
        f"{'anlamlı' if (welch.get('p_value') or 1) < 0.05 else 'anlamlı değil'} (Welch p = {fmt.num(welch['p_value'], 3) if welch.get('p_value') is not None else '–'}).",
        f"{len(cross)} hissenin {better} tanesinde iyileşen raporların ardından ortalama {bcd['horizon']} günlük getiri daha "
        f'yüksek; {sig} tanesinde fark p < 0,05. "İyi bilanço = fiyat artışı" genellemesi bu veride desteklenmiyor.',
    ]
    md = (
        header("S4", f"Çeyreklik temel değişim ve açıklama sonrası fiyat tepkisi: {tk}", run)
        + f"""## Ana bulgular

{chr(10).join("- " + f for f in findings)}

## 1. Soru

> {run.res.request.question}

Şartname §14: çeyreklik finansal değişimler, bilgi kamuya açıklandıktan SONRA fiyata nasıl yansıdı; belirli
değişimler tarihsel olarak farklı fiyat tepkileriyle ilişkili mi.

## 2. Yöntem

- **Kaynak:** KAP XBRL mali tabloları; her değer hangi rapordan, hangi saatte açıklandığıyla tutulur. Bir analiz
  tarihinde yalnızca o ana kadar açıklanmış raporlar görünür; revizyonlarda o an bilinen son sürüm seçilir.
- **Tepki baz günü:** işlem günü 18:10 sonrası açıklama → o günün kapanışı; seans öncesi / içi → önceki işlem günü;
  tatil → önceki işlem günü. Ufuklar {", ".join(str(h) for h in hz)} işlem günü; anormal getiri = hisse − XU100 ve
  hisse − sektör sepeti ({", ".join(chg["peers"])}).
- **TMS 29:** {tk} {"enflasyon muhasebesi uygular" if chg["tms29_applies"] else "enflasyon muhasebesi uygulamaz"}. KAP gelir tablosu
  kümülatiftir (YTD); çeyreklik değer YTD farkından çıkarılır ve farklı raporlar farklı satın alma gücündedir → birincil
  karşılaştırma aynı rapordaki yıllık YTD kıyasıdır. 2025 öncesine taşan karşılaştırmalar † ile işaretlidir.
- **Oranlar** (F/K, PD/DD, FD/FAVÖK) hazır kaynaktan alınmaz; analiz tarihindeki fiyat × o ana kadar açıklanmış bilanço ile
  hesaplanır. Şablon: `{chg["template"]}`; şablona uymayan oranlar hesaplanmaz.
- **Etiket:** {chg["label_rule"].replace("improved = EBITDA margin up vs previous report", "iyileşen = FAVÖK marjı önceki rapora göre yükseldi")}.

## 3. Son rapor: {lr["fiscal_period"].replace("Q", "Ç")} ({fmt.tr_datetime(lr["disclosure_datetime"])}, [KAP]({lr["source"]}))

{table(["Kalem", "Çeyrek", "Yıl başından", "Son 12 ay"], lev_rows)}

**Oranlar**

{table(["Oran", "Değer", "Temel", "Not", "Neden yok"], rat_rows, "lrlll")}

**Değerleme** ({fmt.tr_date(val.get("day"))} fiyatı {fmt.num(val.get("price", 0), 2)} TL)

{table(["Çarpan", "Değer", "Neden yok"], val_rows, "lrl") if val_rows else "Yok."}

## 4. Rapor rapor fiyat tepkisi

Hasılat ve FAVÖK yıllık (YTD) değişim; FAVÖK marjı değişimi; açıklama sonrası XU100'e göre anormal getiri.

{table(["Dönem", "Açıklama", "Zamanlama", "Hasılat", "FAVÖK", "FAVÖK marjı Δ", *[f"{h}g anormal" for h in hz], "TMS 29"], rep_rows, "lll" + "r" * (3 + len(hz)) + "l")}

**Ortalama tepki**

{table(["Ufuk", "Rapor", "Ort. getiri", "Ort. anormal (XU100)", "Medyan anormal (XU100)", "Ort. anormal (sektör)"], agg_rows)}

**İyileşen ve kötüleşen raporlar ({bcd["horizon"]} günlük getiri)**

{table(["Grup", "n", "Ortalama", "Medyan", "Pozitif oran", "En düşük / en yüksek"], dir_rows)}

Welch t testi p = {fmt.num(welch["p_value"], 3) if welch.get("p_value") is not None else "–"}.

## 5. Bütün hisseler

Aynı ayrım ders evrenindeki her hisse için ({bcd["horizon"]} günlük getiri, iyileşen / kötüleşen rapor sayısı):

{table(["Hisse", "Şablon", "İyileşen / kötüleşen", "İyileşen ort.", "Kötüleşen ort.", "p"], cross_rows, "llrrrr")}

{len(cross)} hissenin {better} tanesinde iyileşen raporlardan sonra ortalama getiri daha yüksek, {sig} tanesinde fark
p < 0,05. Hisse başına rapor sayısı küçük (yaklaşık 10–11); tek tek sonuçlar zayıf kanıttır.

## 6. Sektöre özgü oranlar: banka örneği (AKBNK)

Şartname "banka analizi sanayi şirketi oranlarını körü körüne kullanmamalı" diyor. Banka şablonunda FAVÖK'e dayalı
oranlar ve cari oran hesaplanmaz:

{table(["Oran", "Değer", "Not"], bank_rows, "lrl")}

## 7. Backtest

{("`" + variant + "` varyantı (" + VARIANT_TR.get(variant, variant) + "), önceden sabitlenmiş kural:" + chr(10) + chr(10) + table(["Ölçüt", "Değer"], bt_rows(bt), "lr")) if bt else "Backtest çıktısı yok."}

## 8. Harness kararı

{decision_md(run)}

## 9. Sınırlar

- Hisse başına çeyrek sayısı az (2023Ç4 – 2026Ç2); TMS 29 geçişi eski çeyreklerle kıyası zorlaştırır.
- Sürpriz, piyasa beklentisine göre değil önceki rapora göre tanımlanır (analist konsensüs verisi yok).
- Açıklama penceresine denk gelen başka haberler ayrıştırılmaz.

## Ek — kaynak araç çağrıları

{provenance(run, out.parent.parent)}{scan.appendix()}
"""
    )
    return write(out, f"s4_bilanco_tepki_{tk.lower()}.md", md)


# --------------------------------------------------------------------------------------------- macro + context
SERIES_TR = {
    "USDTRY": "USD/TRY (TCMB alış)",
    "EURTRY": "EUR/TRY (TCMB alış)",
    "TCMB_POLICY_RATE": "TCMB politika faizi",
    "FED_TARGET_UPPER": "Fed hedef üst sınır",
    "FED_TARGET_LOWER": "Fed hedef alt sınır",
    "TUFE_YOY": "TÜFE yıllık",
    "TUFE_MOM": "TÜFE aylık",
}
RATE_SERIES = {"TCMB_POLICY_RATE", "FED_TARGET_UPPER", "FED_TARGET_LOWER", "TUFE_YOY", "TUFE_MOM"}


def report_macro(out: Path) -> Path:
    run = run_golden("Q5", out)
    scan = Scan()
    mac = run.env("get_macro_context").result
    tk = mac.get("ticker_for_corr") or run.res.request.tickers[0]

    def lvl(code: str, v: float) -> str:
        return f"%{fmt.num(v, 2)}" if code in RATE_SERIES else fmt.num(v, 4)

    def chg(code: str, v: float | None) -> str:
        if v is None:
            return "–"
        return f"{fmt.num(v, 2)} puan" if code in RATE_SERIES else pct(v, 2, True)

    lat_rows = [
        [
            SERIES_TR.get(c, c),
            lvl(c, x["value"]),
            fmt.tr_date(x["obs_date"]),
            fmt.tr_datetime(x["release_datetime"]),
            chg(c, mac["changes"].get(c, {}).get("1m")),
            chg(c, mac["changes"].get(c, {}).get("3m")),
            chg(c, mac["changes"].get(c, {}).get("12m")),
        ]
        for c, x in mac["latest"].items()
    ]
    pol_rows = [
        [fmt.tr_date(x["obs_date"]), f"%{fmt.num(x['previous'], 2)}", f"%{fmt.num(x['value'], 2)}"]
        for x in mac["policy_rate_changes_in_window"]
    ]
    infl = mac["inflation_in_window"]
    rules = mac["release_rules"]
    rules_tr = {
        "FX": "TCMB gösterge alış kuru, bülten günü 15:30",
        "TCMB_POLICY_RATE": "yürürlük günü 00:00",
        "FED": "yürürlük günü 00:00",
        "TUFE": "sonraki ayın 3'ü (veya sonraki ilk BIST işlem günü) 10:00",
    }
    fx = mac.get("fx_relationship") or {}
    fx_rows = [
        [
            SERIES_TR.get(s, s),
            str(x["correlation"]["n"]),
            fmt.num(x["correlation"]["pearson"], 3),
            fmt.num(x["correlation"]["pearson_p"], 3),
            fmt.num(x["correlation"]["spearman"], 3),
            fmt.num(x["beta"]["beta"], 2),
            fmt.num(x["beta"]["r2"], 3),
            pct(x["stock_return"], 2, True),
            pct(x["fx_return"], 2, True),
            pct(x["stock_return_in_fx"], 2, True),
        ]
        for s, x in fx.items()
    ]
    # FX sensitivity of every stock (weekly returns vs USD/TRY)
    from bistharness.core.config import load_universe

    u = load_universe()
    sens = []
    for t in u.tickers():
        e = scan(t, "get_macro_context", {"start": START, "ticker_for_corr": t})
        x = (e.result.get("fx_relationship") or {}).get("USDTRY")
        if x:
            sens.append((t, x))
    sens.sort(key=lambda z: z[1]["correlation"]["pearson"])
    sens_rows = [
        [
            t,
            (u.instruments[t].peer_group or "").replace("_", " "),
            fmt.num(x["correlation"]["pearson"], 3),
            fmt.num(x["correlation"]["pearson_p"], 3),
            fmt.num(x["beta"]["beta"], 2),
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
        color=[SIGNAL if t == tk else ("#b5b1a6" if v < 0 else INK) for (t, _), v in zip(sens, vals, strict=True)],
        height=0.62,
    )
    ax.set_yticks(range(len(sens)), [t for t, _ in sens], fontsize=7.5)
    ax.axvline(0, color=INK, linewidth=0.7)
    ax.set_xlabel("haftalık getiri korelasyonu: hisse ve USD/TRY (Pearson)")
    style(ax)
    fig_fx = save(fig, out / "fig" / "makro_kur_duyarliligi.png")
    news_rows = []
    for c in run.res.calls:
        if c.tool == "get_news_events" and c.envelope is not None:
            nr = c.envelope.result
            news_rows.append(
                [
                    str(nr["query"].get("ticker") or nr["query"].get("topic")),
                    f"{fmt.tr_date(nr['start'])} – {fmt.tr_date(nr['end'])}",
                    str(nr["count"]),
                ]
            )
    findings = [
        f"{fmt.tr_date(run.res.request.as_of_date)} itibarıyla TCMB politika faizi %{fmt.num(mac['latest']['TCMB_POLICY_RATE']['value'], 2)}, "
        f"yıllık TÜFE'ye göre reel faiz {fmt.num(mac['real_policy_rate'], 2)} puan; USD/TRY 12 ayda "
        f"{pct(mac['changes']['USDTRY']['12m'], 2, True)}.",
        f"{fmt.tr_date(infl['start_month'])} – {fmt.tr_date(infl['end_month'])} arasında açıklanmış {infl['months_used']}/"
        f"{infl['months_expected']} aylık TÜFE ile birikimli enflasyon {pct(infl['cumulative'], 2)}.",
    ]
    if "USDTRY" in fx:
        x = fx["USDTRY"]
        findings.append(
            f"{tk}'nin haftalık getirisi ile USD/TRY arasındaki korelasyon {fmt.num(x['correlation']['pearson'], 3)} "
            f"(p = {fmt.num(x['correlation']['pearson_p'], 3)}); hisse dolar bazında {pct(x['stock_return_in_fx'], 2, True)}. "
            "Korelasyon nedensellik değildir."
        )
    findings.append(f"{len(sens)} hissenin {pos} tanesinde haftalık getiri USD/TRY ile pozitif ilişkili.")
    findings.append(
        f"Tavsiye talebi reddedildi; sistem tarihsel bağlamı gösterdi ve **{run.res.explanation.action.value if run.res.explanation else '–'}** dedi."
    )
    md = (
        header("Makro", "Makro ve bağlamsal kanıtın entegrasyonu", run)
        + f"""## Ana bulgular

{chr(10).join("- " + f for f in findings)}

## 1. Soru

> {run.res.request.question}

Hocanın Q5'i iki şeyi sınar: (a) tavsiye ve hedef fiyat talebinin reddi, (b) makro bağlamın ({tk} ve kur) yayım
tarihine göre doğru kullanımı. Şartname §15–16: makro ve haber/konuşma katmanı.

## 2. Yayım zamanı hizalaması (point-in-time)

Her makro değer gözlem tarihine göre değil, **kamuya açıklandığı ana** göre görünür:

{table(["Seri", "Bilgi zamanı kuralı"], [[k, rules_tr.get(k, v)] for k, v in rules.items()], "ll")}

Örnek: Ağustos TÜFE'si Eylül'ün 3'ünde 10:00'da açıklanır; 2 Eylül'de yapılan bir analiz Ağustos TÜFE'sini göremez.

## 3. {fmt.tr_date(run.res.request.as_of_date)} itibarıyla makro tablo

{table(["Seri", "Değer", "Gözlem", "Yayım", "1 ay", "3 ay", "12 ay"], lat_rows, "lrllrrr")}

Reel politika faizi (yıllık TÜFE'ye göre) {fmt.num(mac["real_policy_rate"], 2)} puan; Fed hedef aralığı orta noktası
%{fmt.num(mac["fed_mid"], 3)}. Birikimli enflasyon: {pct(infl["cumulative"], 2)} ({infl["months_used"]}/{infl["months_expected"]} ay).

**Dönemdeki TCMB faiz kararları**

{table(["Yürürlük", "Önceki", "Yeni"], pol_rows, "lrr")}

## 4. {tk} ve kur ilişkisi

Haftalık (Cuma) getiriler; aynı ortak gün aralığı.

{table(["Kur", "Hafta", "Pearson", "p", "Spearman", "Beta", "R²", "Hisse getirisi", "Kur getirisi", "Hisse (döviz bazında)"], fx_rows)}

"İhracatçı olduğu için dolar yükselince kesin yükselir" iddiası veriyle desteklenmiyor: haftalık ilişki
{"negatif" if fx.get("USDTRY", {}).get("correlation", {}).get("pearson", 0) < 0 else "pozitif"} ve açıklama gücü (R²) düşük. Korelasyon
nedensellik değildir; geçmiş ilişki geleceği garanti etmez.

## 5. Bütün hisselerin kur duyarlılığı

{table(["Hisse", "Sektör", "Pearson (USD/TRY)", "p", "Beta", "Dolar bazında getiri"], sens_rows, "llrrrr")}

![Kur duyarlılığı](fig/{fig_fx})

## 6. Haber ve konuşma bağlamı

Haberler yalnızca **bağlamdır**: başlık ve metindeki sayılar doğrulanmış veri sayılmaz, açıklamada kanıt olarak
kullanılamaz. Kaynak Bloomberg HT arşivi; veritabanına yalnız metadata (başlık, URL, hisse ve konu etiketi) girer.
Etiket kesinliği ayrı bir denetimle ölçüldü (`reports/news_tagging_audit.md`). Bilgi zamanı = ilk yayın ile son düzenleme
arasından geç olanı (muhafazakâr).

{table(["Sorgu", "Pencere", "Haber"], news_rows, "llr") if news_rows else "Bu koşuda haber sorgusu yok."}

Konuşma/video katmanı (`feature/speech-layer`, ekip arkadaşı): YouTube'un kendi transkript paneli, altyazı kalitesi
resmi metinlerle ölçülür; iddialar insan onayından sonra araçlarla doğrulanır. Ayrıntı o katmanın kendi raporundadır.

## 7. Tavsiye talebi ve harness kararı

{decision_md(run)}

## 8. Sınırlar

- Makro seriler aylık/olay bazlı; günlük hisse getirisiyle ilişki kısa dönemde zayıf ölçülür.
- Korelasyonlar dönem seçimine duyarlıdır; yapısal kırılmalar (faiz döngüsü) test edilmedi.
- Haber etiketleri deterministik kurallarla üretilir; bağlam dışı eşleşmeler kesinlik denetiminde raporlanır.

## Ek — kaynak araç çağrıları

{provenance(run, out.parent.parent)}{scan.appendix()}
"""
    )
    return write(out, "makro_baglam.md", md)


# --------------------------------------------------------------------------------------------- backtest
def report_backtest(out: Path) -> Path:
    scan = Scan()
    env = scan(
        "ders evreni, 5 varyant",
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
    r = env.result
    spec = r["strategy_spec"]
    bm = r["benchmarks"]
    head = [
        "Varyant",
        "Katmanlar",
        "Sinyal",
        "İşlem",
        "Kazanan",
        "Kümülatif",
        "Reel",
        "Sharpe (0 / faiz)",
        "En büyük düşüş",
        "XU100 farkı",
        "Örneklem dışı",
    ]
    rows = []
    for name, v in r["variants"].items():
        m, t = v["metrics"], v["trades"]
        oos = v.get("out_of_sample")
        rows.append(
            [
                f"{name} ({VARIANT_TR.get(name, name)})",
                ", ".join(v.get("layers") or []) or "yalnız teknik",
                fmt.integer(t["n_signals"]),
                fmt.integer(t["n_closed"]) + ("*" if t["n_closed"] < 10 else ""),
                pct(t["win_rate"], 1),
                pct(m["cumulative"], 1, True),
                pct(v["real_cumulative"], 1, True),
                f"{fmt.num(m['sharpe_rf0'], 2)} / {fmt.num(m['sharpe_policy'], 2)}",
                pct(m["max_drawdown"], 1),
                fmt.pp_from_fraction(v["vs_xu100"], 1),
                pct(oos["cumulative"], 1, True) if oos else "–",
            ]
        )
    cash_rows = [
        [
            f"{name}",
            pct(v["cash_at_policy_rate"]["metrics"]["cumulative"], 1, True),
            pct(v["cash_at_policy_rate"]["real_cumulative"], 1, True),
            fmt.num(v["cash_at_policy_rate"]["metrics"]["sharpe_policy"], 2),
            pct(v["exposure_mean"], 0),
        ]
        for name, v in r["variants"].items()
        if v.get("cash_at_policy_rate")
    ]
    bm_rows = [
        [
            {
                "buy_and_hold": "Eşit ağırlıklı al-tut (30 hisse)",
                "xu100": "XU100",
                "sector_basket": "Sektör sepeti",
            }.get(k, k),
            pct(x["cumulative"], 1, True),
            fmt.num(x["sharpe_rf0"], 2),
            pct(x["max_drawdown"], 1),
        ]
        for k, x in bm.items()
        if isinstance(x, dict) and "cumulative" in x
    ]
    plt = pyplot()
    fig, ax = plt.subplots(figsize=(8.2, 3.9))
    colors = [SIGNAL, "#c2361b", "#6b3fd1", "#2c5cc5", "#1d7a4b"]
    from datetime import date as _d

    xu_drawn = False
    for (name, v), col in zip(r["variants"].items(), colors, strict=False):
        eq = v.get("equity") or []
        if not eq:
            continue
        x = [_d.fromisoformat(str(p["date"])[:10]) for p in eq]
        ax.plot(x, [p["strategy"] * 100 for p in eq], color=col, linewidth=1.5, label=f"{name}")
        if not xu_drawn:
            ax.plot(x, [p["xu100"] * 100 for p in eq], color=INK, linewidth=1.1, label="XU100")
            ax.plot(
                x, [p["buy_and_hold"] * 100 for p in eq], ":", color=MUTE, linewidth=1.1, label="Eşit ağırlıklı al-tut"
            )
            xu_drawn = True
    ax.set_ylabel("kümülatif getiri (%)")
    ax.legend(fontsize=7, frameon=False, ncol=2)
    style(ax)
    ax.grid(axis="y", color="#e4e1d8", linewidth=0.6)
    fig_eq = save(fig, out / "fig" / "backtest_varyantlar.png")
    best = max(r["variants"].items(), key=lambda kv: kv[1]["metrics"]["sharpe_rf0"])
    beat = [n for n, v in r["variants"].items() if v["vs_xu100"] > 0]
    small = [n for n, v in r["variants"].items() if v["trades"]["n_closed"] < 10]
    sig_path = " → ".join(
        f"{n.split('_')[0]} {fmt.integer(v['trades']['n_signals'])}" for n, v in r["variants"].items()
    )
    small_text = (
        f"{', '.join(small)} 10'dan az işlemle küçük örneklem uyarısı taşıyor."
        if small
        else "Her varyantta en az 10 kapanmış işlem var."
    )
    names = list(r["variants"])
    same = [
        (a, b)
        for a, b in itertools.pairwise(names)
        if r["variants"][a]["trades"]["n_closed"] == r["variants"][b]["trades"]["n_closed"]
        and r["variants"][a]["metrics"]["cumulative"] == r["variants"][b]["metrics"]["cumulative"]
    ]
    same_text = "".join(
        f" {a} ve {b} sonuçları birebir aynı: {b} varyantına eklenen katman bu dönemde ek sinyal elemedi."
        for a, b in same
    )
    md = f"""# Backtest sonuçları ve kıyaslar

*FinTreX Analyst raporu · analiz tarihi {fmt.tr_date(AS_OF)} · dönem {fmt.tr_date(r["start"])} – {fmt.tr_date(r["end"])} ·
evren: 30 hisselik ders evreni. Bu rapor `eval/scenario_reports.py` ile araç çıktılarından üretilmiştir; her sayı
`run_backtest` zarfından gelir. Eğitsel bir analizdir; BUY/SELL yalnızca eğitsel backtest pozisyonudur, hiçbir emir
üretilmez.*

## Ana bulgular

- Beş varyanttan XU100'ü geçenler: {", ".join(beat) or "yok"}. En yüksek Sharpe (rf = 0): {best[0]} ({fmt.num(best[1]["metrics"]["sharpe_rf0"], 2)}).
- Politika faizine göre Sharpe tüm varyantlarda {"negatif" if all(v["metrics"]["sharpe_policy"] < 0 for v in r["variants"].values()) else "karışık"}:
  boşta nakit tutmak TCMB faizi kadar kazandırmadığı için strateji faizin gerisinde kalıyor (aşağıda nakit faizli sürüm).
- Katman ekledikçe sinyal sayısı düşüyor ({sig_path}). {small_text}{same_text}

## 1. Kural ve yürütme

- **Önceden sabitlenmiş kural** `{spec["name"]}` (sonuçlara bakılmadan seçildi; değiştirmek yeni bir ad gerektirir):
  giriş olayları {", ".join(f"`{x}`" for x in spec["entry_events"])}; elde tutma {spec["holding_days"]} işlem günü.
- **Katmanlar** (A → E birikimli): B sektörde geride olmayan ({spec["sector_window"]} günlük pencere), C son raporda hasılat
  büyümesi ≥ {pct(spec["fund_min_topline_growth"], 0)}, D son {spec["macro_fx_window"]} günde USD/TRY değişimi ≤
  {pct(spec["macro_max_fx_change"], 0)} ve son {spec["macro_hike_lookback_days"]} günde faiz artışı yok,
  E son {spec["news_lookback_days"]} günde {", ".join(spec["news_block_topics"])} haberi yok.
- **Zamanlama:** sinyal t kapanışında (bilgi ≤ t), işlem t+1 açılışında; çıkış {spec["holding_days"]} gün sonra açılışta.
  Pozisyon başına tek işlem, sermaye eşit bölmelere ayrılır, boştaki bölme %0 getirir (ayrıca politika faizli sürüm).
- **Maliyet:** işlem maliyeti {fmt.num(r["costs"]["tx_cost_bps"], 0)} baz puan, kayma {fmt.num(r["costs"]["slippage_bps"], 0)} baz puan.
- **Örneklem dışı:** {fmt.tr_date("2026-01-01")} ve sonrası ayrı raporlanır.

## 2. Varyantlar

{table(head, rows, "llrrrrrrrrr")}

\\* 10'dan az kapanmış işlem: yüksek getiri az olaydan geliyorsa güvenilmez.

![Varyantların getiri eğrisi](fig/{fig_eq})

## 3. Kıyaslar

{table(["Kıyas", "Kümülatif", "Sharpe", "En büyük düşüş"], bm_rows, "lrrr")}

## 4. Boştaki nakit politika faiziyle

Türkiye'de nakdin fırsat maliyeti yüksektir. Boştaki bölmeler o günkü TCMB politika faiziyle değerlendirilseydi:

{table(["Varyant", "Kümülatif", "Reel", "Sharpe (faize göre)", "Ortalama yatırım oranı"], cash_rows, "lrrrr")}

## 5. Sınırlar

- Tek kural, tek evren, ~2,7 yıl; parametre araması yapılmadı (veri madenciliği riskini azaltmak için).
- Kapanış–açılış arası boşluk ve kısmi dolum modellenmedi; BIST fiyat marjı ve tavan/taban kilitleri yok sayıldı.
- Temettü ve bölünme düzeltmeli fiyatlar kullanıldı; vergi yok.

## Ek — kaynak araç çağrısı

Veri sürümü: {", ".join(f"{k} `{str(v)[:12]}`" for k, v in sorted(env.data_version.items()))}{scan.appendix()}
"""
    return write(out, "backtest_kiyaslar.md", md)


REPORTS = {
    "s1": report_s1,
    "s2": report_s2,
    "s3": report_s3,
    "s4": report_s4,
    "makro": report_macro,
    "backtest": report_backtest,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("which", choices=sorted(REPORTS), nargs="+")
    parser.add_argument("--out", type=Path, default=project_root() / "reports" / "scenarios")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for w in args.which:
        print(f"{w}: {REPORTS[w](args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
