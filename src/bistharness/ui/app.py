"""Streamlit human-in-the-loop UI (CLAUDE.md §8): run an analysis, inspect states / evidence / gate / backtest, record a
human review, browse the decision log and replay a decision.

    uv run streamlit run src/bistharness/ui/app.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bistharness.core.config import load_universe, project_root
from bistharness.core.enums import AnalyticalAction, ReviewVerdict, Scenario
from bistharness.harness.factory import build_config, default_memory_path, ollama_client, tool_context
from bistharness.harness.intent import understand_question
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.policy import load_policy
from bistharness.harness.replay import replay_analysis
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.runner import AnalysisResult, run_analysis


@st.cache_data(show_spinner="Soru anlaşılıyor…")
def _understand(text: str, as_of_iso: str, mode: str, model: str) -> dict[str, Any]:
    """Cached per (question, date, mode, model): Streamlit reruns the script on every widget change."""
    client = ollama_client(load_policy(), model) if mode != "rules" else None
    u = understand_question(
        text, as_of=date.fromisoformat(as_of_iso), universe=load_universe(), client=client, mode=mode
    )
    return {
        "request": u.request.model_dump(mode="json") if u.request else None,
        "method": u.method,
        "message": u.message_tr,
        "override": u.advice_override,
        "added": list(u.tickers_added),
        "dropped": list(u.tickers_dropped),
        "source": u.ticker_source,
    }


SCENARIO_TR = {
    Scenario.S1_SECTOR_CATCH_UP: "S1 · Sektörde geride kalma / yakalama",
    Scenario.S2_WEEKDAY_PATTERN: "S2 · Haftanın günü örüntüsü",
    Scenario.S3_TECHNICAL_REVERSAL: "S3 · Teknik dönüş olayları",
    Scenario.S4_FUNDAMENTAL_REACTION: "S4 · Çeyreklik temel değişim ve fiyat tepkisi",
    Scenario.SAFETY_ADVICE_REQUEST: "Güvenlik · Tavsiye/hedef fiyat talebi",
}
ACTION_COLOR = {
    "HOLD": "#64748b",
    "WATCH": "#2563eb",
    "INVESTIGATE": "#d97706",
    "POTENTIAL_CATCH_UP_CANDIDATE": "#059669",
    "TECHNICAL_REVERSAL_CANDIDATE": "#059669",
    "FUNDAMENTAL_IMPROVEMENT_CANDIDATE": "#059669",
    "REJECT_SIGNAL": "#7c3aed",
    "ANALYSIS_UNSAFE": "#dc2626",
}
GATE_COLOR = {
    "PASS": "#059669",
    "PASS_WITH_WARNINGS": "#2563eb",
    "INVESTIGATE": "#d97706",
    "ANALYSIS_UNSAFE": "#dc2626",
    "HARD_BLOCK": "#dc2626",
}


@st.cache_resource
def _ctx() -> Any:
    return tool_context()


@st.cache_resource
def _memory() -> EpisodicMemory:
    return EpisodicMemory(default_memory_path())


@st.cache_data
def _golden() -> dict[str, Any]:
    path = Path(project_root()) / "eval" / "golden_questions.json"
    return json.loads(path.read_text(encoding="utf-8"))


def badge(text: str, color: str) -> str:
    return (
        f"<span style='background:{color};color:white;padding:4px 10px;border-radius:6px;font-weight:600'>{text}</span>"
    )


def sidebar() -> tuple[AnalysisRequest | None, str, str | None]:
    st.sidebar.header("Analiz")
    golden = _golden()
    mode = st.sidebar.radio("Soru kaynağı", ["Golden sorular", "Serbest soru"], horizontal=True)
    as_of = st.sidebar.date_input(
        "as_of_date (analiz tarihi)",
        date.fromisoformat(golden["as_of_date"]),
        min_value=date(2024, 3, 1),
        max_value=date(2026, 11, 19),
    )
    explainer = st.sidebar.selectbox(
        "Açıklayıcı",
        ["template", "llm"],
        format_func=lambda x: "Kural tabanlı şablon" if x == "template" else "Yerel LLM (Ollama)",
    )
    model = st.sidebar.text_input("Ollama modeli", load_policy().llm["model"]) if explainer == "llm" else None
    req: AnalysisRequest | None = None
    if mode == "Golden sorular":
        qs = {q["id"]: q for q in golden["questions"]}
        qid = st.sidebar.selectbox("Soru", list(qs), format_func=lambda k: f"{k} · {qs[k]['title']}")
        q = qs[qid]
        st.sidebar.caption(q["question"])
        req = AnalysisRequest(
            question=q["question"],
            scenario=Scenario(q["scenario"]),
            tickers=q["tickers"],
            as_of_date=as_of,
            params=q.get("params", {}),
            advice_requested=bool(q.get("advice_requested", False)),
        )
    else:
        text = st.sidebar.text_area("Soru", "ASELS'te alt Bollinger dokunuşlarından sonraki 5 günlük getiri nasıl?")
        how = st.sidebar.radio(
            "Soru anlama",
            ["llm", "rules", "manual"],
            format_func=lambda x: {
                "llm": "Yerel model (önerilen)",
                "rules": "Anahtar kelime kuralları",
                "manual": "Elle seç",
            }[x],
        )
        if how != "manual":
            u = _understand(text, as_of.isoformat(), how, model or str(load_policy().llm["model"]))
            if u["request"] is not None:
                req = AnalysisRequest.model_validate(u["request"])
                st.sidebar.success(f"{SCENARIO_TR[req.scenario]} · {', '.join(req.tickers)} ({u['method']})")
                if u["override"]:
                    st.sidebar.info("Soruda tavsiye ifadesi var: güvenlik senaryosu uygulandı.")
                if u["added"] or u["dropped"]:
                    st.sidebar.info(
                        "Hisseler soruya göre düzeltildi: "
                        + (f"eklendi {', '.join(u['added'])} " if u["added"] else "")
                        + (f"çıkarıldı {', '.join(u['dropped'])}" if u["dropped"] else "")
                    )
                if u["source"] == "sector":
                    st.sidebar.caption("Hisseler soruda adı geçen sektörden seçildi; gerekirse 'Elle seç' kullanın.")
            else:
                st.sidebar.warning(f"Soru analiz edilmedi: {u['message']}")
        else:
            sc = st.sidebar.selectbox("Senaryo", list(Scenario), format_func=lambda s: SCENARIO_TR[s])
            tickers = st.sidebar.multiselect("Hisseler", list(load_universe().tickers()), default=["ASELS"])
            if tickers and sc is not None:
                req = AnalysisRequest(question=text, scenario=sc, tickers=tickers, as_of_date=as_of)
    return req, explainer, model


def show_result(res: AnalysisResult) -> None:
    e = res.explanation
    c1, c2, c3 = st.columns([2, 2, 3])
    c1.markdown(
        "**Eğitsel analitik durum**<br>"
        + badge(e.action.value if e else "-", ACTION_COLOR.get(e.action.value if e else "", "#64748b")),
        unsafe_allow_html=True,
    )
    c2.markdown(
        "**Risk / veri kalitesi kapısı**<br>" + badge(res.gate.value, GATE_COLOR[res.gate.value]),
        unsafe_allow_html=True,
    )
    c3.markdown(f"**Analiz** `{res.analysis_id}`<br>**Karar** `{res.decision_id}`", unsafe_allow_html=True)
    tabs = st.tabs(["Açıklama", "Kanıtlar", "İş akışı", "Backtest", "İnsan onayı"])
    with tabs[0]:
        if e:
            st.markdown(e.text_tr.replace("\n", "  \n"))
            st.caption(
                f"Açıklayıcı: {e.explainer} · deneme sayısı: {len(e.attempts)} · güvenli şablona düşüldü: "
                f"{'evet' if e.fallback_used else 'hayır'} · kural tabanlı referans eylem: "
                f"{e.teacher_action.value if e.teacher_action else '-'}"
            )
            for i, a in enumerate(e.attempts, 1):
                with st.expander(f"Deneme {i}: denetim {'GEÇTİ' if a.validation.ok else 'KALDI'}"):
                    st.json({"checks": a.validation.checks, "errors": a.validation.errors})
                    st.code(a.raw[:4000], language="json")
    with tabs[1]:
        com = pd.DataFrame(
            [
                {"E#": c["id"], "kanıt": c["claim_tr"], "araç": c["tool"], "tür": c["kind"]}
                for c in res.bundle.get("committed", [])
            ]
        )
        st.subheader("Committed Evidence Set")
        st.dataframe(com, hide_index=True, use_container_width=True)
        with st.expander(f"Observed context ({len(res.bundle.get('observed', []))} aday)"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {"O#": c["id"], "anahtar": c["key"], "kanıt": c["claim_tr"]}
                        for c in res.bundle.get("observed", [])
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
        if res.gate_reasons:
            st.subheader("Kapı bulguları")
            st.dataframe(pd.DataFrame(res.gate_reasons), hide_index=True, use_container_width=True)
    with tabs[2]:
        st.dataframe(
            pd.DataFrame(
                [
                    {"state": s.state.value, "durum": s.status.value, "çağrı": len(s.calls), "not": s.reason or ""}
                    for s in res.states
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        calls = pd.DataFrame(
            [
                {
                    "state": c.state.value,
                    "araç": c.tool,
                    "kaynak": c.origin,
                    "geçerli": c.valid,
                    "durum": c.envelope.status.value if c.envelope else "-",
                    "call_id": (c.envelope.call_id[:12] if c.envelope else ""),
                    "hata": c.error or "",
                }
                for c in res.calls
            ]
        )
        st.dataframe(calls, hide_index=True, use_container_width=True)
    with tabs[3]:
        env = None
        for c in res.calls:
            if c.tool == "run_backtest" and c.envelope is not None and c.state.value == "RUN_BACKTEST":
                env = c.envelope
        if env is None:
            st.info("Backtest çıktısı yok.")
        else:
            for v, block in env.result["variants"].items():
                st.subheader(f"Varyant {v}")
                if block.get("equity"):
                    eq = pd.DataFrame(block["equity"])
                    fig = go.Figure()
                    for col, name in (
                        ("strategy", "Strateji"),
                        ("xu100", "XU100"),
                        ("buy_and_hold", "Eşit ağırlıklı al-tut"),
                    ):
                        fig.add_trace(go.Scatter(x=eq["date"], y=eq[col] * 100, name=name, mode="lines"))
                    fig.update_layout(
                        yaxis_title="Kümülatif getiri (%)", height=380, margin={"l": 10, "r": 10, "t": 30}
                    )
                    st.plotly_chart(fig, use_container_width=True)
                m, t = block["metrics"], block["trades"]
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "kümülatif": m["cumulative"],
                                "reel": block["real_cumulative"],
                                "Sharpe (rf=0)": m["sharpe_rf0"],
                                "Sharpe (politika)": m["sharpe_policy"],
                                "max düşüş": m["max_drawdown"],
                                "işlem": t["n_closed"],
                                "kazanan oranı": t["win_rate"],
                                "XU100 farkı": block["vs_xu100"],
                            }
                        ]
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
            st.caption("BUY/SELL yalnızca eğitsel backtest pozisyonudur; hiçbir emir üretilmez.")
    with tabs[4]:
        review_form(res)


def review_form(res: AnalysisResult) -> None:
    if not res.decision_id:
        return
    mem = _memory()
    for r in mem.reviews(res.decision_id):
        st.success(
            f"{r['created_at']} · {r['reviewer']} · {r['verdict']} · {r['modified_action'] or ''} · {r['reason']}"
        )
    with st.form(f"review-{res.decision_id}"):
        verdict = st.radio(
            "Karar",
            [ReviewVerdict.ACCEPT.value, ReviewVerdict.MODIFY.value, ReviewVerdict.REJECT.value],
            horizontal=True,
        )
        new_action = st.selectbox("Değiştirilmiş eylem (MODIFY)", [a.value for a in AnalyticalAction])
        reason = st.text_area("Gerekçe (zorunlu)")
        reviewer = st.text_input("İnceleyen", "öğrenci")
        if st.form_submit_button("Kaydet"):
            if not reason.strip():
                st.error("Gerekçe zorunlu.")
            else:
                mem.add_review(
                    res.decision_id,
                    reviewer=reviewer,
                    verdict=verdict,
                    reason=reason,
                    modified_action=new_action if verdict == "MODIFY" else None,
                )
                st.success("İnceleme karar kaydına eklendi.")


def history() -> None:
    mem = _memory()
    rows = mem.analyses(100)
    if not rows:
        st.info("Henüz kayıtlı analiz yok.")
        return
    df = pd.DataFrame(rows)[
        ["created_at", "analysis_id", "scenario", "as_of_date", "gate", "action", "explainer", "decision_id"]
    ]
    st.dataframe(df, hide_index=True, use_container_width=True)
    ids = [r["decision_id"] for r in rows if r["decision_id"]]
    if not ids:
        return
    did = st.selectbox("Karar", ids)
    with_llm = st.checkbox("LLM adımını da aynı tohumla yeniden üret (yavaş)")
    if st.button("Replay"):
        client = ollama_client(load_policy()) if with_llm else None
        with st.spinner("Araçlar aynı girdilerle yeniden çalıştırılıyor..."):
            rep = replay_analysis(did, _ctx(), mem, client)
        st.write(
            f"Veri sürümü aynı: **{rep.data_version_match}** · tüm araç çıktıları aynı: **{rep.tools_match}**"
            + (f" · LLM çıktısı aynı: **{rep.llm_match}**" if rep.llm_compared else "")
        )
        st.dataframe(pd.DataFrame([c.__dict__ for c in rep.calls]), hide_index=True, use_container_width=True)
        if rep.llm_diff:
            st.code(rep.llm_diff)


def main() -> None:
    st.set_page_config(page_title="BIST Agentic Harness", layout="wide")
    st.title("Integrated BIST 100 Agentic Financial Analytics Harness")
    st.caption(
        "Eğitsel araştırma aracı · yatırım tavsiyesi değildir · tüm hesaplar deterministik Python araçlarıyla, "
        "as_of tarihine kadar bilinen veriyle yapılır · LLM yalnızca yerel olarak çalışır."
    )
    page = st.sidebar.radio("Sayfa", ["Analiz", "Karar kaydı & Replay"])
    if page == "Karar kaydı & Replay":
        history()
        return
    req, explainer, model = sidebar()
    if st.sidebar.button("Analizi çalıştır", type="primary", disabled=req is None) and req is not None:
        with st.spinner("17 adımlı iş akışı çalışıyor..."):
            cfg = build_config(explainer=explainer, model=model, memory=_memory())
            st.session_state["result"] = run_analysis(req, _ctx(), cfg)
    res = st.session_state.get("result")
    if res is not None:
        show_result(res)
    else:
        st.info("Soldan bir golden soru seçip analizi çalıştırın.")


main()
