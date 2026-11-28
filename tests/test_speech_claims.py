from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from bistharness.core.speech_claims import ClaimSegment, ReviewRecord, source_numbers
from bistharness.harness.claims import cached_extract, export_reviews, extraction_key, grounded_quote
from bistharness.harness.llm_client import ScriptedClient


def test_local_extraction_preserves_source_and_resumes_after_failure(tmp_path: Path) -> None:
    segment = ClaimSegment("fixture", 0, 60, "2026-03-05 19:31:24", "Türk Hava Yolları yüzde 40 arttı.", ("THYAO",))
    valid = {
        "subject": "Türk Hava Yolları",
        "claim_type": "fundamental_value",
        "evidence_index": 0,
        "metric": None,
        "direction": "up",
        "horizon_days": None,
        "stance": "positive",
        "certainty": "high",
    }
    client = ScriptedClient(
        responses=[
            "{",
            json.dumps({"claims": [valid, {**valid, "subject": "MGROS"}, {**valid, "horizon_days": 10}]}),
            '{"claims":[]}',
        ]
    )
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE extraction(key TEXT PRIMARY KEY, claims TEXT, rejected INTEGER)")
    allowed = {"THYAO", "MACRO"}
    with pytest.raises(ValueError):
        cached_extract(db, client, segment, allowed, "scripted", "old")
    assert db.execute("SELECT count(*) FROM extraction").fetchone() == (0,)
    records, rejected, reused = cached_extract(db, client, segment, allowed, "scripted", "old")
    assert len(records) == 1 and rejected == 2 and not reused
    assert records[0].claim.quote == segment.text and records[0].claim.subject == "THYAO"
    assert cached_extract(db, client, segment, allowed, "scripted", "old") == (records, 2, True)
    assert cached_extract(db, client, segment, allowed, "scripted", "changed") == ([], 0, False)
    assert len(client.calls) == 3
    db.close()

    path = tmp_path / "fixture.jsonl"
    active = {segment.start: extraction_key(segment, "old", allowed)}
    export_reviews(path, records, active)
    reviewed = records[0].model_copy(update={"reviewed": True, "review_note": "Kaynakla karşılaştırıldı."})
    path.write_text(reviewed.model_dump_json() + "\n", encoding="utf-8")
    export_reviews(path, records, active)
    assert ReviewRecord.model_validate_json(path.read_text(encoding="utf-8")) == reviewed
    with pytest.raises(ValueError, match="superseded"):
        export_reviews(path, [], {segment.start: extraction_key(segment, "changed", allowed)})


def test_numeric_quotes_cannot_clip_source_tokens() -> None:
    assert grounded_quote("Artış yüzde 40,5 oldu.", "yüzde 40") is None
    assert grounded_quote("Margin was 40%.", "40") is None
    assert grounded_quote("Artış %40 oldu.", "40 oldu") is None
    assert source_numbers("yüzde 40,5; %12 ve 3.75 percent") == [("pct", 40.5), ("pct", 12), ("pct", 3.75)]
