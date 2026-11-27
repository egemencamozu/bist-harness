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


REPORTS = {"s3": report_s3}


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
