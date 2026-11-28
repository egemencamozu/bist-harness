"""FinTreX Analyst web UI (bistharness.ui.web) on the synthetic snapshot: every endpoint, the live progress of a full
17-state run, human review, replay, and the offline guarantees (no CDN, local bind by default)."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from bistharness.ui.web.server import STATES, STATIC, create_app
from tests.test_tools import _ctx


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    memory = tmp_path_factory.mktemp("web") / "episodic.sqlite"
    with TestClient(create_app(_ctx(False), memory, llm_enabled=False)) as c:
        yield c


def _run(client: TestClient, request: dict[str, Any]) -> dict[str, Any]:
    r = client.post("/api/analyze", json={"request": request, "explainer": "template", "planner": "scenario"})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(600):
        snap = client.get(f"/api/jobs/{job_id}").json()
        if snap["status"] != "running":
            break
        time.sleep(0.05)
    assert snap["status"] == "done", snap["error"]
    return snap


@pytest.fixture(scope="module")
def s3(client: TestClient) -> dict[str, Any]:
    meta = client.get("/api/meta").json()
    q3 = next(g for g in meta["golden"] if g["id"] == "Q3")
    return _run(client, {**q3["request"], "start": "2025-01-01"})


def test_static_front_end_is_self_contained(client: TestClient) -> None:
    html = client.get("/").text
    assert "FinTreX Analyst" in html
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/vendor/plotly.min.js").status_code == 200  # served from the installed plotly package
    for path in [p for p in STATIC.rglob("*") if p.suffix in {".html", ".css", ".js"}]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(src|href)=[\"']https?://", text), f"{path.name} loads a remote resource"
        assert not re.search(r"fetch\([\"'`]https?://", text), f"{path.name} calls a remote API"


def test_meta_status_and_system(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    assert meta["product"] == "FinTreX Analyst"
    assert [g["id"] for g in meta["golden"]] == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    assert [s["state"] for s in meta["states"]] == [s.value for s in STATES]
    assert {"CHECK_DATA_QUALITY", "RUN_BACKTEST", "RISK_GATE"} <= set(meta["mandatory"])
    assert len(meta["actions"]) == 8
    status = client.get("/api/status").json()
    assert status["online"] is False and status["busy"] is False  # llm disabled: no Ollama call
    assert set(client.get("/api/system").json()) == {"bakeoff", "ablation", "intent", "e2e", "golden"}
    tape = client.get("/api/tape", params={"as_of": "2026-09-10"}).json()["rows"]
    assert tape and all(r["date"] <= "2026-09-10" for r in tape)  # the ticker tape is point-in-time too


def test_model_options_are_refused_without_a_local_model(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    r = client.post("/api/analyze", json={"request": meta["golden"][2]["request"], "explainer": "llm"})
    assert r.status_code == 503


def test_understand_with_rules(client: TestClient) -> None:
    ok = client.post("/api/understand", json={"question": "ASELS alt Bollinger dokunuşu", "as_of": "2026-09-10"}).json()
    assert ok["ok"] and ok["method"] == "rules" and ok["tickers"][0]["ticker"] == "ASELS"
    no = client.post("/api/understand", json={"question": "bitcoin ne olur", "as_of": "2026-09-10"}).json()
    assert no["ok"] is False and no["message"]
    assert client.post("/api/understand", json={"question": "", "as_of": "2026-09-10"}).status_code == 400


def test_full_run_reports_every_state_and_its_payload(s3: dict[str, Any]) -> None:
    steps = {s["state"]: s for s in s3["steps"]}
    assert set(steps) == {s.value for s in STATES}
    assert all(s["status"] in {"DONE", "skipped"} for s in steps.values())
    assert steps["RISK_GATE"]["status"] == "DONE" and steps["RISK_GATE"]["calls"]
    res = s3["result"]
    assert res["scenario"] == "S3_TECHNICAL_REVERSAL" and res["decision_id"]
    assert res["action"] and res["gate"] and res["text"]
    assert res["committed"] and all(c["id"].startswith("E") for c in res["committed"])
    assert res["backtest"] and res["backtest"]["variants"]
    assert "ASELS" in res["prices"]
    assert max(res["prices"]["ASELS"]["dates"]) <= res["request"]["as_of_date"]  # charts are PIT too


def test_review_and_replay(client: TestClient, s3: dict[str, Any]) -> None:
    did = s3["result"]["decision_id"]
    assert client.post("/api/review", json={"decision_id": did, "verdict": "ACCEPT", "reason": ""}).status_code == 400
    bad = {"decision_id": did, "verdict": "MODIFY", "reason": "x", "modified_action": "BUY"}
    assert client.post("/api/review", json=bad).status_code == 400
    ok = {"decision_id": did, "verdict": "MODIFY", "reason": "örneklem küçük", "modified_action": "INVESTIGATE"}
    reviews = client.post("/api/review", json=ok).json()["reviews"]
    assert reviews[-1]["verdict"] == "MODIFY" and reviews[-1]["modified_action"] == "INVESTIGATE"
    rep = client.post("/api/replay", json={"decision_id": did, "llm": False}).json()
    assert rep["tools_match"] and rep["n_match"] == rep["n_calls"] > 0
    rows = client.get("/api/history").json()["rows"]
    assert any(r["decision_id"] == did and r["review"] == "MODIFY" for r in rows)
    detail = client.get(f"/api/decision/{did}").json()
    assert detail["evidence"] and detail["reviews"]
    assert client.get("/api/decision/D-nope").status_code == 404


def test_default_bind_is_local() -> None:
    from bistharness.ui.web import __main__ as cli

    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert 'default="127.0.0.1"' in src
