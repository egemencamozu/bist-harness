"""Speech ingest (data/ingest/speech.py): transcript parsing, segments, caption quality, snapshot, PIT. Synthetic text."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from bistharness.core.config import Settings, project_root
from bistharness.core.errors import SnapshotIntegrityError
from bistharness.core.pit import PITRepository
from bistharness.data.ingest import speech
from bistharness.data.ingest.news import TAGS_FILE, Tagger

TAGGER = Tagger.load(project_root() / TAGS_FILE)

PANEL = """Transkript
0:00
merhaba arkadaşlar bugün bilançolara bakıyoruz
0:04
4 saniye
Türk Hava Yolları net kârını açıkladı
1:02
Migros tarafında da güçlü bir çeyrek var
1:15 son olarak piyasaya bakalım
"""


def test_parse_accepts_both_panel_layouts_and_skips_labels() -> None:
    cues = speech.parse_transcript(PANEL)
    assert [c.start for c in cues] == [0, 4, 62, 75]
    assert cues[1].text == "Türk Hava Yolları net kârını açıkladı"  # the "4 saniye" label is not text
    assert cues[3].text == "son olarak piyasaya bakalım"
    assert speech.parse_transcript("1:02:03\nbir saat sonra")[0].start == 3723


def test_backwards_timestamps_are_a_paste_error() -> None:
    with pytest.raises(ValueError, match="backwards"):
        speech.parse_transcript("0:10\na\n0:05\nb")


def test_segments_group_cues_into_windows() -> None:
    segs = speech.segment_cues(speech.parse_transcript(PANEL), duration=90)
    assert [(s.start, s.end) for s in segs] == [(0, 62), (62, 90)]
    assert "Türk Hava Yolları" in segs[0].text and segs[1].text.startswith("Migros")


def test_caption_wer_against_the_official_text() -> None:
    official = "Politika faizini yüzde 40 seviyesinde sabit tuttuk. Enflasyon beklentileri iyileşiyor."
    assert speech.aligned_wer(official, official) == 0.0
    # captions lower-cased, one word misheard, plus a Q&A the speech text does not contain
    caps = "politika faizini yüzde 40 seviyesinde sabit tuttuk enflasyon beklentiler iyileşiyor soru cevap kısmı"
    assert speech.aligned_wer(official, caps) == pytest.approx(1 / 10)
    assert speech.aligned_wer("%40", "yüzde 40") == 0.0
    assert speech.aligned_wer(official, "tamamen başka bir konuşma") == 1.0


def _project(tmp: Path, videos: list[dict[str, str]], files: dict[str, str]) -> Settings:
    manual = tmp / "data" / "manual"
    (manual / "transcripts").mkdir(parents=True)
    head = ",".join(speech.VIDEO_COLUMNS)
    lines = [head] + [",".join(v.get(c, "") for c in speech.VIDEO_COLUMNS) for v in videos]
    (manual / "videos.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name, text in files.items():
        (manual / "transcripts" / name).write_text(text, encoding="utf-8")
    raw = {"paths": {"db": "data/db/bist.sqlite", "raw": "data/raw", "manual": "data/manual"}}
    (tmp / "data" / "db").mkdir(parents=True)
    return Settings(root=tmp, raw=raw)


VIDEOS = [
    {
        "source_id": "v_off",
        "channel": "Resmi",
        "speaker": "A",
        "published_at": "2026-03-01 11:30:00",
        "duration_s": "",
        "transcript_kind": "youtube_captions",
        "quality_from": "self",
    },
    {
        "source_id": "v_fb",
        "channel": "Kanal",
        "speaker": "B",
        "published_at": "2026-03-05 19:31:24",
        "duration_s": "90",
        "transcript_kind": "youtube_captions",
        "quality_from": "v_off",
    },
    {"source_id": "v_late", "published_at": "2026-12-01 10:00:00", "quality_from": ""},
    {"source_id": "v_none", "published_at": "2026-03-02 10:00:00", "quality_from": ""},
]
FILES = {
    "v_off.txt": "0:00\npolitika faizini yüzde 40 seviyesinde sabit tuttuk\n",
    "v_off.official.txt": "Politika faizini yüzde 40 seviyesinde sabit tuttuk.",
    "v_fb.txt": PANEL,
    "v_late.txt": "0:00\nsonra yayımlandı",
}


def test_ingest_end_to_end_is_point_in_time(tmp_path: Path) -> None:
    s = _project(tmp_path, VIDEOS, FILES)
    summary = speech.run(s, "2026-11-20", tagger=TAGGER)
    rep = {v.source_id: v for v in summary.videos}
    assert rep["v_off"].quality == 1.0 and rep["v_fb"].quality == 1.0  # borrowed from the official video
    assert rep["v_late"].skipped == "PUBLISHED_AFTER_SNAPSHOT" and rep["v_none"].skipped == "TRANSCRIPT_MISSING"
    assert rep["v_fb"].tickers == ["MGROS", "THYAO"] and summary.segments == 3
    conn = sqlite3.connect(s.db_path)
    rows = conn.execute("SELECT source_id, segment_start, topics FROM speech_segments ORDER BY 1, 2").fetchall()
    conn.close()
    assert rows[0][:2] == ("v_fb", 0.0) and "THYAO" in json.loads(rows[0][2]) and "earnings" in json.loads(rows[0][2])
    repo = PITRepository(s.db_path)
    assert repo.speech_segments(as_of=date(2026, 3, 4), topic="THYAO").data.empty  # video not published yet
    assert len(repo.speech_segments(as_of=date(2026, 3, 5), topic="THYAO").data) == 1


def test_changed_transcript_needs_a_new_snapshot(tmp_path: Path) -> None:
    s = _project(tmp_path, VIDEOS, FILES)
    speech.run(s, "2026-11-20", tagger=TAGGER)
    (tmp_path / "data" / "manual" / "transcripts" / "v_none.txt").write_text("0:00\nyeni", encoding="utf-8")
    with pytest.raises(SnapshotIntegrityError, match="new --snapshot"):
        speech.run(s, "2026-11-20", tagger=TAGGER)
    assert speech.run(s, "2026-11-21", tagger=TAGGER).segments == 4


def test_video_list_is_fixed_and_well_formed() -> None:
    videos = speech.read_videos(project_root() / "data" / "manual" / "videos.csv")
    assert len(videos) == 7 and all(v.published_at < "2026-09-10" for v in videos)  # before the golden as_of
    ids = {v.source_id for v in videos}
    assert all(v.quality_from in ids | {"self"} for v in videos)
