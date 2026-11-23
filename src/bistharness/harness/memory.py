"""Episodic memory (CLAUDE.md §8): every analysis as state -> tool calls -> evidence -> LLM -> decision -> review.

A separate SQLite file (default data/db/episodic.sqlite) so the market snapshot DB stays read-only. Tool envelopes are
stored whole (inputs, data_version, output_hash) so `replay_analysis` can re-run them on the same snapshot.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bistharness.core.hashing import canonical_json

DDL = """
CREATE TABLE IF NOT EXISTS analyses (
    analysis_id   TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    question      TEXT NOT NULL,
    request_json  TEXT NOT NULL,
    scenario      TEXT NOT NULL,
    as_of_date    TEXT NOT NULL,
    planner       TEXT NOT NULL,
    explainer     TEXT NOT NULL,
    model         TEXT,
    model_digest  TEXT,
    policy_sha256 TEXT NOT NULL,
    data_version  TEXT NOT NULL,
    status        TEXT NOT NULL,           -- RUNNING | DONE | FAILED
    gate          TEXT,
    action        TEXT,
    decision_id   TEXT
);
CREATE TABLE IF NOT EXISTS state_log (
    analysis_id TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    state       TEXT NOT NULL,
    status      TEXT NOT NULL,             -- DONE | SKIPPED_NOT_APPLICABLE | FAILED
    reason      TEXT,
    n_calls     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (analysis_id, seq)
);
CREATE TABLE IF NOT EXISTS tool_calls (
    analysis_id   TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    state         TEXT NOT NULL,
    tool          TEXT NOT NULL,
    origin        TEXT NOT NULL,           -- plan | llm | harness_default | harness
    valid         INTEGER NOT NULL,        -- 0 = invalid_tool_call (not permitted / bad input)
    error         TEXT,
    arguments     TEXT NOT NULL,
    call_id       TEXT,
    output_hash   TEXT,
    status        TEXT,
    envelope_json TEXT,
    PRIMARY KEY (analysis_id, seq)
);
CREATE TABLE IF NOT EXISTS evidence (
    analysis_id  TEXT NOT NULL,
    evidence_id  TEXT NOT NULL,
    key          TEXT NOT NULL,
    tool         TEXT NOT NULL,
    call_id      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    claim_tr     TEXT NOT NULL,
    display_json TEXT NOT NULL,
    PRIMARY KEY (analysis_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS llm_calls (
    analysis_id   TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    purpose       TEXT NOT NULL,           -- explanation | planning
    model         TEXT NOT NULL,
    model_digest  TEXT,
    prompt_hash   TEXT,
    messages_json TEXT NOT NULL,
    raw_output    TEXT NOT NULL,
    validation    TEXT,
    seconds       REAL,
    PRIMARY KEY (analysis_id, seq)
);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id    TEXT PRIMARY KEY,
    analysis_id    TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    action         TEXT NOT NULL,
    text_tr        TEXT NOT NULL,
    cited_json     TEXT NOT NULL,
    gate           TEXT NOT NULL,
    bundle_id      TEXT,
    fallback_used  INTEGER NOT NULL,
    teacher_action TEXT,
    teacher_rule   TEXT
);
CREATE TABLE IF NOT EXISTS human_reviews (
    decision_id     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    reviewer        TEXT NOT NULL,
    verdict         TEXT NOT NULL,          -- ACCEPT | MODIFY | REJECT
    modified_action TEXT,
    reason          TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _j(x: Any) -> str:
    return canonical_json(x)


class EpisodicMemory:
    def __init__(self, path: Path | str = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(DDL)

    # ----------------------------------------------------------------- writes
    def start(
        self,
        analysis_id: str,
        *,
        question: str,
        request: dict[str, Any],
        scenario: str,
        as_of: str,
        planner: str,
        explainer: str,
        policy_sha256: str,
        data_version: dict[str, str],
    ) -> None:
        self.conn.execute(
            "INSERT INTO analyses (analysis_id, created_at, question, request_json, scenario, as_of_date, planner, "
            "explainer, policy_sha256, data_version, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                analysis_id,
                _now(),
                question,
                _j(request),
                scenario,
                as_of,
                planner,
                explainer,
                policy_sha256,
                _j(data_version),
                "RUNNING",
            ),
        )
        self.conn.commit()

    def log_state(self, analysis_id: str, seq: int, state: str, status: str, reason: str | None, n_calls: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO state_log VALUES (?,?,?,?,?,?)", (analysis_id, seq, state, status, reason, n_calls)
        )
        self.conn.commit()

    def log_tool_call(
        self,
        analysis_id: str,
        seq: int,
        *,
        state: str,
        tool: str,
        origin: str,
        valid: bool,
        arguments: dict[str, Any],
        error: str | None = None,
        envelope: dict[str, Any] | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO tool_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                analysis_id,
                seq,
                state,
                tool,
                origin,
                int(valid),
                error,
                _j(arguments),
                envelope.get("call_id") if envelope else None,
                envelope.get("output_hash") if envelope else None,
                envelope.get("status") if envelope else None,
                _j(envelope) if envelope else None,
            ),
        )
        self.conn.commit()

    def log_evidence(self, analysis_id: str, committed: list[dict[str, Any]]) -> None:
        self.conn.execute("DELETE FROM evidence WHERE analysis_id = ?", (analysis_id,))
        self.conn.executemany(
            "INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)",
            [
                (analysis_id, c["id"], c["key"], c["tool"], c["call_id"], c["kind"], c["claim_tr"], _j(c["display"]))
                for c in committed
            ],
        )
        self.conn.commit()

    def log_llm_call(
        self,
        analysis_id: str,
        seq: int,
        *,
        purpose: str,
        model: str,
        digest: str,
        prompt_hash: str,
        messages: list[dict[str, str]],
        raw: str,
        validation: dict[str, Any] | None,
        seconds: float,
    ) -> None:
        self.conn.execute(
            "INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                analysis_id,
                seq,
                purpose,
                model,
                digest,
                prompt_hash,
                _j(messages),
                raw,
                _j(validation) if validation is not None else None,
                seconds,
            ),
        )
        self.conn.commit()

    def save_decision(
        self,
        decision_id: str,
        analysis_id: str,
        *,
        action: str,
        text_tr: str,
        cited: list[str],
        gate: str,
        bundle_id: str | None,
        fallback_used: bool,
        teacher_action: str | None,
        teacher_rule: str | None,
        model: str | None,
        model_digest: str | None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                decision_id,
                analysis_id,
                _now(),
                action,
                text_tr,
                _j(cited),
                gate,
                bundle_id,
                int(fallback_used),
                teacher_action,
                teacher_rule,
            ),
        )
        self.conn.execute(
            "UPDATE analyses SET status='DONE', gate=?, action=?, decision_id=?, model=?, model_digest=? "
            "WHERE analysis_id=?",
            (gate, action, decision_id, model, model_digest, analysis_id),
        )
        self.conn.commit()

    def fail(self, analysis_id: str, reason: str) -> None:
        self.conn.execute(
            "UPDATE analyses SET status='FAILED', action='ANALYSIS_UNSAFE' WHERE analysis_id=?", (analysis_id,)
        )
        self.log_state(analysis_id, 999, "LOG_AND_CLOSE", "FAILED", reason[:500], 0)

    def add_review(
        self, decision_id: str, *, reviewer: str, verdict: str, reason: str, modified_action: str | None = None
    ) -> None:
        if not reason.strip():
            raise ValueError("a human review needs a reason")
        self.conn.execute(
            "INSERT INTO human_reviews VALUES (?,?,?,?,?,?)",
            (decision_id, _now(), reviewer, verdict, modified_action, reason),
        )
        self.conn.commit()

    # ----------------------------------------------------------------- reads
    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def analyses(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM analyses ORDER BY created_at DESC, analysis_id DESC LIMIT ?", (limit,))

    def analysis(self, analysis_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,))
        return rows[0] if rows else None

    def decision(self, decision_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM decisions WHERE decision_id = ?", (decision_id,))
        return rows[0] if rows else None

    def tool_calls(self, analysis_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM tool_calls WHERE analysis_id = ? ORDER BY seq", (analysis_id,))

    def states(self, analysis_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM state_log WHERE analysis_id = ? ORDER BY seq", (analysis_id,))

    def llm_calls(self, analysis_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM llm_calls WHERE analysis_id = ? ORDER BY seq", (analysis_id,))

    def evidence(self, analysis_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT * FROM evidence WHERE analysis_id = ? ORDER BY CAST(SUBSTR(evidence_id, 2) AS INTEGER)",
            (analysis_id,),
        )
        for r in rows:
            r["display"] = json.loads(r.pop("display_json"))
        return rows

    def reviews(self, decision_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM human_reviews WHERE decision_id = ? ORDER BY created_at", (decision_id,))
