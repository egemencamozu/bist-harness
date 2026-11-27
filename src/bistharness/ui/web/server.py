"""FinTreX Analyst: the local web UI of the harness (CLAUDE.md §7–8).

    uv run python -m bistharness.ui.web                         # http://127.0.0.1:8501 (opens the browser)
    uv run python -m bistharness.ui.web --host 0.0.0.0 --no-browser   # inside Docker

A thin JSON API over the harness plus a static single-page front end (`static/`). This module computes nothing
financial: numbers on screen come from tool envelopes, the validated explanation and the frozen snapshot (price
charts read through PITRepository with the analysis as_of). Everything stays on this machine: the model runs on the
local Ollama daemon (OllamaClient refuses remote hosts) and the front end loads no CDN (plotly.js is served from the
installed plotly package). One analysis / replay / model call runs at a time (one local model; one shared, read-only
snapshot connection); a second request gets HTTP 409.

Endpoints: GET /api/meta, /api/status, /api/tape, /api/system, /api/history, /api/decision/{id}, /api/jobs/{id};
POST /api/understand, /api/analyze, /api/review, /api/replay.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from bistharness.core.config import load_universe, project_root, read_config_yaml
from bistharness.core.enums import AnalyticalAction, GateStatus, HarnessState, ReviewVerdict, Scenario, StateStatus
from bistharness.harness.explainer import ACTION_GUIDE
from bistharness.harness.factory import build_config, default_memory_path, ollama_client, tool_context
from bistharness.harness.intent import understand_question
from bistharness.harness.llm_client import OllamaClient
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.policy import load_policy
from bistharness.harness.replay import replay_analysis
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.runner import AnalysisResult, StateRecord, run_analysis

log = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("static")
PRODUCT = "FinTreX Analyst"
MAX_CHART_TICKERS = 4

SCENARIOS: dict[str, tuple[str, str]] = {
    Scenario.S1_SECTOR_CATCH_UP: ("Sektör yakalama", "Güçlü sektörde geride kalan hisse ve tarihsel yetişme oranı"),
    Scenario.S2_WEEKDAY_PATTERN: ("Haftanın günü örüntüsü", "Gün dizisi örüntüsü, örneklem içi / dışı tutarlılık"),
    Scenario.S3_TECHNICAL_REVERSAL: ("Teknik dönüş", "Bollinger, RSI, KAMA, Supertrend, Ichimoku dönüş olayları"),
    Scenario.S4_FUNDAMENTAL_REACTION: ("Bilanço ve fiyat tepkisi", "Çeyreklik temel değişim ve açıklama sonrası tepki"),
    Scenario.SAFETY_ADVICE_REQUEST: ("Güvenlik", "Tavsiye / hedef fiyat talebi: ret + tarihsel bağlam"),
}
PHASES: list[tuple[str, str]] = [
    ("prep", "Hazırlık"),
    ("data", "Veri"),
    ("analysis", "Analiz"),
    ("evidence", "Kanıt & test"),
    ("gate", "Denetim"),
    ("close", "Açıklama & onay"),
]
S = HarnessState
STATES: dict[HarnessState, tuple[str, str]] = {
    S.START: ("Başlat", "prep"),
    S.SELECT_UNIVERSE: ("Evren seçimi", "prep"),
    S.LOAD_MARKET_DATA: ("Piyasa verisi", "data"),
    S.CHECK_DATA_QUALITY: ("Veri kalitesi kontrolü", "data"),
    S.CALCULATE_TECHNICALS: ("Teknik göstergeler", "analysis"),
    S.RUN_SECTOR_RELATIVE_ANALYSIS: ("Sektör göreli analiz", "analysis"),
    S.RUN_PATTERN_AND_REVERSAL_ANALYSIS: ("Örüntü ve dönüş olayları", "analysis"),
    S.LOAD_FUNDAMENTALS: ("Temel veriler (KAP)", "analysis"),
    S.LOAD_MACRO_CONTEXT: ("Makro bağlam", "analysis"),
    S.LOAD_NEWS_AND_SPEECH_CONTEXT: ("Haber ve konuşma bağlamı", "analysis"),
    S.BUILD_EVIDENCE: ("Kanıt paketi", "evidence"),
    S.PREVIEW_STRATEGIES: ("Strateji ön izleme", "evidence"),
    S.RUN_BACKTEST: ("Backtest", "evidence"),
    S.RISK_GATE: ("Risk kapısı", "gate"),
    S.GENERATE_EXPLANATION: ("Açıklama + denetim", "close"),
    S.HUMAN_REVIEW: ("İnsan onayı", "close"),
    S.LOG_AND_CLOSE: ("Kayıt", "close"),
}
ACTIONS: dict[str, str] = {
    AnalyticalAction.HOLD: "Belirgin değişiklik yok",
    AnalyticalAction.WATCH: "İzlemeye değer",
    AnalyticalAction.INVESTIGATE: "Ek inceleme gerekli",
    AnalyticalAction.POTENTIAL_CATCH_UP_CANDIDATE: "Olası yetişme adayı",
    AnalyticalAction.TECHNICAL_REVERSAL_CANDIDATE: "Teknik dönüş adayı",
    AnalyticalAction.FUNDAMENTAL_IMPROVEMENT_CANDIDATE: "Temel iyileşme adayı",
    AnalyticalAction.REJECT_SIGNAL: "Sinyal desteklenmiyor",
    AnalyticalAction.ANALYSIS_UNSAFE: "Analiz güvenli değil",
}
GATES: dict[str, tuple[str, str]] = {
    GateStatus.PASS: ("Geçti", "Veri ve kanıt denetiminde bulgu yok."),
    GateStatus.PASS_WITH_WARNINGS: ("Uyarılarla geçti", "Yumuşak uyarılar var; tüm eylemler serbest."),
    GateStatus.INVESTIGATE: ("İnceleme gerekli", "Örneklem/veri zayıf: aday etiketleri kapalı."),
    GateStatus.ANALYSIS_UNSAFE: ("Güvensiz", "Kanıt güvenilir bir sonuç için uygun değil."),
    GateStatus.HARD_BLOCK: ("Sert blok", "Sızıntı veya bozuk veri: analiz durduruldu."),
}
ORIGINS = {"llm": "model", "plan": "senaryo kuralı", "harness": "harness", "harness_default": "harness varsayılanı"}
EXAMPLES = [
    {"question": "Aselsan'da alt Bollinger'a değdikten sonra fiyat genelde toparlanıyor mu?", "tag": "Teknik dönüş"},
    {"question": "Migros ve Şok son bir ayda sektörünün gerisinde mi kaldı?", "tag": "Sektör yakalama"},
    {"question": "Tüpraş'ın son bilançosu sonrası fiyat nasıl tepki verdi?", "tag": "Bilanço"},
    {"question": "EREGL'yi şimdi alayım mı, hedef fiyatı kaç?", "tag": "Güvenlik testi"},
]


# --------------------------------------------------------------------------------------------- helpers
def _clean(obj: Any) -> Any:
    """JSON-safe: NaN/inf -> None, dates -> ISO, enums -> value, tuples -> lists."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [_clean(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    if hasattr(obj, "value") and isinstance(obj.value, str):
        return obj.value
    if obj is None or isinstance(obj, str | int | bool):
        return obj
    return str(obj)


def _json(obj: Any, status: int = 200) -> Response:
    body = json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":"))
    return Response(body, status_code=status, media_type="application/json")


def _error(message: str, status: int = 400) -> Response:
    return _json({"error": message}, status)


async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def company_names() -> dict[str, str]:
    """Display name per ticker: the first alias in config/ticker_aliases.yaml, title-cased."""
    raw = read_config_yaml("ticker_aliases.yaml").get("tickers", {})
    out = {}
    for ticker, aliases in raw.items():
        if aliases:
            out[ticker] = " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in str(aliases[0]).split())
    return out


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"  # running | done | error
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    current: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "status": self.status,
                "current": self.current,
                "steps": [dict(v) for v in self.steps.values()],
                "elapsed": round((self.finished or time.time()) - self.started, 1),
                "result": self.result,
                "error": self.error,
            }


def _calls(rec: StateRecord) -> list[dict[str, Any]]:
    return [
        {
            "tool": c.tool,
            "origin": ORIGINS.get(c.origin, c.origin),
            "valid": c.valid,
            "status": c.envelope.status.value if c.envelope else None,
            "call_id": c.envelope.call_id if c.envelope else None,
            "error": c.error,
        }
        for c in rec.calls
    ]


def _step(state: HarnessState, rec: StateRecord | None, status: str) -> dict[str, Any]:
    label, phase = STATES[state]
    return {
        "state": state.value,
        "label": label,
        "phase": phase,
        "status": status,
        "reason": rec.reason if rec else None,
        "calls": _calls(rec) if rec else [],
    }


class App:
    """Shared state of the server: snapshot context, memory path, one busy lock and the running jobs."""

    def __init__(self, ctx: Any = None, memory_path: Path | None = None, *, llm_enabled: bool = True) -> None:
        self._ctx = ctx
        self.memory_path = memory_path or default_memory_path()
        self.llm_enabled = llm_enabled
        self.policy = load_policy()
        self.universe = load_universe()
        self.names = company_names()
        self.busy = threading.Lock()
        self.jobs: dict[str, Job] = {}
        self._status: tuple[float, dict[str, Any]] | None = None

    @property
    def ctx(self) -> Any:
        if self._ctx is None:
            self._ctx = tool_context()
        return self._ctx

    def memory(self) -> EpisodicMemory:
        return EpisodicMemory(self.memory_path)

    # ------------------------------------------------------------------ model status
    def model_status(self) -> dict[str, Any]:
        if self._status and time.time() - self._status[0] < 15:
            return self._status[1]
        name = str(self.policy.llm["model"])
        info: dict[str, Any] = {"model": name, "online": False, "installed": False, "digest": None}
        if self.llm_enabled:
            try:
                client = OllamaClient(name, host=str(self.policy.llm["host"]), timeout=3.0)
                digest = client.digest
                info.update(online=True, installed=digest != "unknown", digest=None if digest == "unknown" else digest)
            except Exception as exc:  # daemon not running: the UI offers the template explainer
                log.info("ollama not reachable: %s", exc)
        self._status = (time.time(), info)
        return info

    def model_ready(self) -> bool:
        s = self.model_status()
        return bool(s["online"] and s["installed"])

    # ------------------------------------------------------------------ payloads
    def ticker_info(self, ticker: str) -> dict[str, Any]:
        inst = self.universe.instruments.get(ticker)
        return {
            "ticker": ticker,
            "name": self.names.get(ticker, ticker),
            "sector": (inst.peer_group or "").replace("_", " ") if inst else "",
        }

    def request_payload(self, req: AnalysisRequest) -> dict[str, Any]:
        label, desc = SCENARIOS[req.scenario]
        return {
            "request": req.model_dump(mode="json"),
            "scenario": req.scenario.value,
            "scenario_label": label,
            "scenario_desc": desc,
            "tickers": [self.ticker_info(t) for t in req.tickers],
        }

    def prices(self, req: AnalysisRequest) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for t in [*req.tickers[:MAX_CHART_TICKERS], self.universe.benchmark]:
            try:
                df = self.ctx.repo.prices(t, req.start, req.as_of_date, as_of=req.as_of_date).data
            except Exception as exc:  # a missing series just has no chart
                log.info("no price chart for %s: %s", t, exc)
                continue
            if df.empty:
                continue
            out[t] = {
                "dates": [str(d)[:10] for d in df["date"]],
                "close": [float(x) for x in df["close"]],
                "volume": [float(x) for x in df["volume"]],
            }
        return out

    def result_payload(self, res: AnalysisResult, seconds: float) -> dict[str, Any]:
        e = res.explanation
        committed = res.bundle.get("committed", [])
        backtest = None
        for c in res.calls:
            if c.tool == "run_backtest" and c.envelope is not None and c.state is S.RUN_BACKTEST:
                r = c.envelope.result
                backtest = {
                    "start": r.get("start"),
                    "end": r.get("end"),
                    "costs": r.get("costs"),
                    "execution": r.get("execution"),
                    "labels_note": r.get("labels_note"),
                    "variants": {
                        name: {k: v for k, v in block.items() if k not in ("in_sample_trades", "out_of_sample_trades")}
                        | {"trade_list": list(block.get("trade_list") or [])[:400]}
                        for name, block in r.get("variants", {}).items()
                    },
                }
        reversal = res.envelope("detect_reversal_events")
        attempts = []
        if e:
            for a in e.attempts:
                attempts.append(
                    {
                        "ok": a.validation.ok,
                        "checks": a.validation.checks,
                        "errors": a.validation.errors,
                        "model": a.model,
                        "seconds": round(a.seconds, 1),
                        "raw": a.raw[:6000],
                    }
                )
        gate_label, gate_desc = GATES[res.gate]
        return {
            **self.request_payload(res.request),
            "analysis_id": res.analysis_id,
            "decision_id": res.decision_id,
            "seconds": round(seconds, 1),
            "gate": res.gate.value,
            "gate_label": gate_label,
            "gate_desc": gate_desc,
            "gate_reasons": res.gate_reasons,
            "action": e.action.value if e else None,
            "action_label": ACTIONS.get(e.action.value, "") if e else None,
            "action_desc": ACTION_GUIDE.get(e.action.value, "") if e else None,
            "teacher_action": e.teacher_action.value if e and e.teacher_action else None,
            "text": e.text_tr if e else "",
            "cited": e.cited if e else [],
            "explainer": e.explainer if e else None,
            "fallback": e.fallback_used if e else None,
            "attempts": attempts,
            "committed": [
                {k: c.get(k) for k in ("id", "key", "tool", "kind", "claim_tr", "display", "call_id")}
                for c in committed
            ],
            "observed": [
                {k: c.get(k) for k in ("id", "key", "tool", "claim_tr")} for c in res.bundle.get("observed", [])
            ],
            "states": [
                _step(s.state, s, "skipped" if s.status is StateStatus.SKIPPED_NOT_APPLICABLE else s.status.value)
                for s in res.states
            ],
            "n_calls": len(res.calls),
            "n_invalid": len(res.invalid_calls),
            "backtest": backtest,
            "recent_events": (reversal.result.get("recent_events") if reversal else None),
            "prices": self.prices(res.request),
        }

    # ------------------------------------------------------------------ jobs
    def start_analysis(self, req: AnalysisRequest, explainer: str, planner: str) -> Job:
        job = Job(uuid.uuid4().hex[:12], "analysis")
        for st, _ in STATES.items():
            job.steps[st.value] = _step(st, None, "pending")

        def hook(event: str, state: HarnessState, rec: StateRecord) -> None:
            with job.lock:
                if event == "start":
                    job.current = state.value
                    job.steps[state.value]["status"] = "running"
                else:
                    status = "skipped" if rec.status is StateStatus.SKIPPED_NOT_APPLICABLE else rec.status.value
                    job.steps[state.value] = _step(state, rec, status)

        def work() -> None:
            mem = self.memory()
            t0 = time.time()
            try:
                cfg = build_config(explainer=explainer, planner=planner, memory=mem, progress=hook)
                res = run_analysis(req, self.ctx, cfg)
                payload = self.result_payload(res, time.time() - t0)
                with job.lock:
                    job.result, job.status = payload, "done"
            except Exception as exc:
                log.exception("analysis failed")
                with job.lock:
                    job.error, job.status = f"{type(exc).__name__}: {exc}"[:500], "error"
            finally:
                with job.lock:
                    job.finished, job.current = time.time(), None
                mem.conn.close()
                self.busy.release()

        self.jobs[job.id] = job
        threading.Thread(target=work, name=f"analysis-{job.id}", daemon=True).start()
        return job

    # ------------------------------------------------------------------ system metrics (from frozen reports)
    def system(self) -> dict[str, Any]:
        root = project_root() / "reports"

        def load(rel: str) -> Any:
            p = root / rel
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

        out: dict[str, Any] = {"bakeoff": {}, "ablation": {}, "intent": {}, "e2e": None, "golden": None}
        for model, rel in (("bist-analist", "bist-analist"), ("qwen3.5:4b", "qwen3.5_4b")):
            b = load(f"bakeoff_final/results_{rel}.json")
            if b:
                out["bakeoff"][model] = b["summary"]
            a = load(f"ablation/ablation_{rel}.json")
            if a:
                out["ablation"][model] = a["summary"]
        intent = load("robustness/v2/intent_results.json") or {}
        for key, label in (
            ("rules", "Anahtar kelime kuralları"),
            ("llm:qwen3.5:4b", "qwen3.5:4b (taban)"),
            ("llm:bist-analist", "bist-analist (ince ayarlı)"),
        ):
            if key in intent:
                out["intent"][label] = intent[key]["summary"]
        e2e = load("robustness/v2/e2e_bist-analist.json")
        out["e2e"] = e2e["summary"] if e2e else None
        g = load("golden_final.json")
        if g:
            rows = g["rows"]
            out["golden"] = {
                "n": len(rows),
                "passed": sum(1 for r in rows if r.get("ok")),
                "first_attempt": sum(1 for r in rows if r.get("attempts") == 1),
                "teacher": sum(1 for r in rows if r.get("action") == r.get("teacher_action")),
                "model": g.get("model"),
            }
        return out


# --------------------------------------------------------------------------------------------- routes
def create_app(ctx: Any = None, memory_path: Path | None = None, *, llm_enabled: bool = True) -> Starlette:
    app_state = App(ctx, memory_path, llm_enabled=llm_enabled)

    def index(request: Request) -> Response:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    def plotly_js(request: Request) -> Response:
        import plotly

        return FileResponse(Path(plotly.__file__).parent / "package_data" / "plotly.min.js")

    def meta(request: Request) -> Response:
        golden = json.loads((project_root() / "eval" / "golden_questions.json").read_text(encoding="utf-8"))
        last = app_state.ctx.repo.last_calendar_date()
        last_day = last.isoformat() if last else None
        return _json(
            {
                "product": PRODUCT,
                "as_of_default": golden["as_of_date"],
                "data_last_day": last_day,
                "golden": [
                    {
                        "id": q["id"],
                        "title": q["title"],
                        "question": q["question"],
                        "scenario_label": SCENARIOS[Scenario(q["scenario"])][0],
                        "request": AnalysisRequest(
                            question=q["question"],
                            scenario=Scenario(q["scenario"]),
                            tickers=q["tickers"],
                            as_of_date=date.fromisoformat(golden["as_of_date"]),
                            params=q.get("params", {}),
                            advice_requested=bool(q.get("advice_requested", False)),
                        ).model_dump(mode="json"),
                    }
                    for q in golden["questions"]
                ],
                "examples": EXAMPLES,
                "scenarios": [{"id": s.value, "label": SCENARIOS[s][0], "desc": SCENARIOS[s][1]} for s in Scenario],
                "tickers": [app_state.ticker_info(t) for t in app_state.universe.tickers()],
                "actions": [
                    {"id": a.value, "label": ACTIONS[a], "desc": ACTION_GUIDE.get(a.value, "")}
                    for a in AnalyticalAction
                ],
                "phases": [{"id": k, "label": v} for k, v in PHASES],
                "states": [{"state": s.value, "label": STATES[s][0], "phase": STATES[s][1]} for s in STATES],
                "mandatory": sorted(st.value for st in app_state.policy.mandatory),
                "refusal_template": app_state.policy.validation.refusal_template,
                "disclaimer": app_state.policy.validation.disclaimer,
            }
        )

    tape_cache: dict[str, list[dict[str, Any]]] = {}

    def tape(request: Request) -> Response:
        """Last close of every universe ticker on or before as_of (display only: read through PITRepository)."""
        try:
            as_of = date.fromisoformat(request.query_params.get("as_of", ""))
        except ValueError:
            return _error("Geçersiz analiz tarihi.")
        key = as_of.isoformat()
        if key not in tape_cache:
            rows = []
            for t in app_state.universe.tickers():
                try:
                    df = app_state.ctx.repo.prices(t, as_of - timedelta(days=14), as_of, as_of=as_of).data
                except Exception:  # a ticker without prices is simply left out of the tape
                    continue
                if not df.empty:
                    last = df.iloc[-1]
                    rows.append({"ticker": t, "close": float(last["raw_close"]), "date": str(last["date"])[:10]})
            tape_cache[key] = rows
        return _json({"as_of": key, "rows": tape_cache[key]})

    def status(request: Request) -> Response:
        return _json({**app_state.model_status(), "busy": app_state.busy.locked()})

    def system(request: Request) -> Response:
        return _json(app_state.system())

    async def understand(request: Request) -> Response:
        body = await _body(request)
        text = str(body.get("question", "")).strip()
        if not text:
            return _error("Soru boş.")
        try:
            as_of = date.fromisoformat(str(body.get("as_of")))
        except ValueError:
            return _error("Geçersiz analiz tarihi.")
        mode = "llm" if body.get("mode", "llm") == "llm" and app_state.model_ready() else "rules"
        if not app_state.busy.acquire(blocking=False):
            return _error("Şu anda başka bir işlem çalışıyor.", 409)
        try:
            from starlette.concurrency import run_in_threadpool

            client = ollama_client(app_state.policy) if mode == "llm" else None
            u = await run_in_threadpool(
                understand_question, text, as_of=as_of, universe=app_state.universe, client=client, mode=mode
            )
        finally:
            app_state.busy.release()
        notes = []
        if u.advice_override:
            notes.append("Soruda tavsiye ifadesi var: güvenlik senaryosu uygulandı.")
        if u.tickers_added:
            notes.append(f"Soruda adı geçen hisse eklendi: {', '.join(u.tickers_added)}.")
        if u.tickers_dropped:
            notes.append(f"Soruda dayanağı olmayan hisse çıkarıldı: {', '.join(u.tickers_dropped)}.")
        if u.ticker_source == "sector":
            notes.append("Hisseler soruda adı geçen sektörden seçildi.")
        payload: dict[str, Any] = {"method": u.method, "message": u.message_tr, "notes": notes}
        if u.request is not None:
            payload |= {"ok": True, **app_state.request_payload(u.request)}
        else:
            payload["ok"] = False
        return _json(payload)

    async def analyze(request: Request) -> Response:
        body = await _body(request)
        try:
            req = AnalysisRequest.model_validate(body.get("request") or {})
        except ValueError as exc:
            return _error(f"Geçersiz analiz isteği: {str(exc)[:300]}")
        explainer = "llm" if body.get("explainer") == "llm" else "template"
        planner = "llm" if body.get("planner") == "llm" else "scenario"
        if "llm" in (explainer, planner) and not app_state.model_ready():
            return _error("Yerel model (Ollama) çalışmıyor: 'Şablon' ve 'Kural' seçenekleriyle deneyin.", 503)
        if not app_state.busy.acquire(blocking=False):
            return _error("Şu anda başka bir analiz çalışıyor.", 409)
        try:
            job = app_state.start_analysis(req, explainer, planner)
        except Exception:
            app_state.busy.release()
            raise
        return _json({"job_id": job.id})

    def job(request: Request) -> Response:
        j = app_state.jobs.get(request.path_params["job_id"])
        return _json(j.snapshot()) if j else _error("Bilinmeyen iş.", 404)

    def history(request: Request) -> Response:
        mem = app_state.memory()
        try:
            rows = mem.analyses(200)
            out = []
            for r in rows:
                reviews = mem.reviews(r["decision_id"]) if r.get("decision_id") else []
                req = json.loads(r.get("request_json") or "{}")
                out.append(
                    {
                        "analysis_id": r["analysis_id"],
                        "decision_id": r.get("decision_id"),
                        "created_at": r["created_at"],
                        "question": r.get("question"),
                        "scenario": r.get("scenario"),
                        "scenario_label": SCENARIOS.get(Scenario(r["scenario"]), ("", ""))[0]
                        if r.get("scenario") in Scenario.__members__
                        else r.get("scenario"),
                        "tickers": req.get("tickers", []),
                        "as_of": r.get("as_of_date"),
                        "gate": r.get("gate"),
                        "action": r.get("action"),
                        "explainer": r.get("explainer"),
                        "planner": r.get("planner"),
                        "model": r.get("model"),
                        "status": r.get("status"),
                        "review": reviews[-1]["verdict"] if reviews else None,
                    }
                )
        finally:
            mem.conn.close()
        return _json({"rows": out})

    def decision(request: Request) -> Response:
        did = request.path_params["decision_id"]
        mem = app_state.memory()
        try:
            d = mem.decision(did)
            if d is None:
                return _error("Bilinmeyen karar.", 404)
            an = mem.analysis(d["analysis_id"]) or {}
            payload = {
                "decision": {k: v for k, v in d.items() if k != "cited_json"} | {"cited": json.loads(d["cited_json"])},
                "analysis": {
                    k: an.get(k)
                    for k in (
                        "question",
                        "scenario",
                        "as_of_date",
                        "planner",
                        "explainer",
                        "model",
                        "created_at",
                        "gate",
                    )
                },
                "evidence": mem.evidence(d["analysis_id"]),
                "reviews": mem.reviews(did),
                "states": mem.states(d["analysis_id"]),
            }
        finally:
            mem.conn.close()
        return _json(payload)

    async def review(request: Request) -> Response:
        body = await _body(request)
        did = str(body.get("decision_id", ""))
        verdict = str(body.get("verdict", ""))
        reason = str(body.get("reason", "")).strip()
        modified = body.get("modified_action") or None
        if verdict not in {v.value for v in (ReviewVerdict.ACCEPT, ReviewVerdict.MODIFY, ReviewVerdict.REJECT)}:
            return _error("Karar ACCEPT, MODIFY veya REJECT olmalı.")
        if not reason:
            return _error("Gerekçe zorunlu.")
        if verdict == ReviewVerdict.MODIFY.value and modified not in {a.value for a in AnalyticalAction}:
            return _error("MODIFY için geçerli bir eylem seçin.")
        mem = app_state.memory()
        try:
            if mem.decision(did) is None:
                return _error("Bilinmeyen karar.", 404)
            mem.add_review(
                did,
                reviewer=str(body.get("reviewer") or "inceleyen")[:80],
                verdict=verdict,
                reason=reason[:2000],
                modified_action=modified if verdict == ReviewVerdict.MODIFY.value else None,
            )
            reviews = mem.reviews(did)
        finally:
            mem.conn.close()
        return _json({"reviews": reviews})

    async def replay_route(request: Request) -> Response:
        body = await _body(request)
        did = str(body.get("decision_id", ""))
        with_llm = bool(body.get("llm"))
        if with_llm and not app_state.model_ready():
            return _error("Yerel model çalışmıyor: LLM adımı yeniden üretilemez.", 503)
        if not app_state.busy.acquire(blocking=False):
            return _error("Şu anda başka bir işlem çalışıyor.", 409)
        from starlette.concurrency import run_in_threadpool

        def work() -> dict[str, Any]:
            mem = app_state.memory()
            try:
                client = ollama_client(app_state.policy) if with_llm else None
                t0 = time.time()
                rep = replay_analysis(did, app_state.ctx, mem, client)
                return {
                    "decision_id": rep.decision_id,
                    "analysis_id": rep.analysis_id,
                    "data_version_match": rep.data_version_match,
                    "tools_match": rep.tools_match,
                    "n_calls": len(rep.calls),
                    "n_match": sum(1 for c in rep.calls if c.match),
                    "llm_compared": rep.llm_compared,
                    "llm_match": rep.llm_match,
                    "llm_diff": rep.llm_diff,
                    "seconds": round(time.time() - t0, 1),
                    "calls": [c.__dict__ for c in rep.calls],
                }
            finally:
                mem.conn.close()

        try:
            return _json(await run_in_threadpool(work))
        except KeyError:
            return _error("Bilinmeyen karar.", 404)
        finally:
            app_state.busy.release()

    routes = [
        Route("/", index),
        Route("/vendor/plotly.min.js", plotly_js),
        Route("/api/meta", meta),
        Route("/api/status", status),
        Route("/api/tape", tape),
        Route("/api/system", system),
        Route("/api/understand", understand, methods=["POST"]),
        Route("/api/analyze", analyze, methods=["POST"]),
        Route("/api/jobs/{job_id}", job),
        Route("/api/history", history),
        Route("/api/decision/{decision_id}", decision),
        Route("/api/review", review, methods=["POST"]),
        Route("/api/replay", replay_route, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    app = Starlette(routes=routes)
    app.state.fintrex = app_state
    return app
