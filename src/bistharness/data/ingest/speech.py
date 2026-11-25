"""Speech ingest: the fixed video list + pasted YouTube transcripts -> speech_segments (contextual evidence only).

Inputs (CLAUDE.md §14, spec §16: the list is fixed before any experiment):
- `data/manual/videos.csv`: one row per video (URL, channel, speaker, publication time in Europe/Istanbul local,
  transcript kind, selection reason).
- `data/manual/transcripts/<source_id>.txt`: the transcript exactly as YouTube's own "Show transcript" panel shows
  it (timestamp lines followed by text). Copying the panel is a feature the platform offers; nothing is downloaded,
  no platform protection is bypassed (spec §6). Missing or empty files are skipped and reported.
- `data/manual/transcripts/<source_id>.official.txt` (official videos only): the institution's own published text
  (TCMB speech text, Fed press-conference transcript). It measures the caption quality: `aligned_wer` compares the
  official words with the caption words over the span where they overlap. A video with `quality_from: <id>` takes
  the quality measured on video `<id>` (same caption system and language); empty -> unknown.

Point in time: every segment of a video is known from `published_at` (upload time; for a live broadcast the END of
the broadcast, conservative). Videos published on or after the snapshot day are left out.

Segments: consecutive caption cues grouped into ~`SEGMENT_SECONDS` windows; `segment_end` = next segment start (the
last one ends at the video duration). Tickers: company names / exact tokens from `config/news.yaml` (the news
tagger, exclusions included); topics: the news topic lexicon. Tickers are stored in `topics` too, so
`get_speech_features(source_id_or_topic="THYAO")` finds the segments naming THYAO. `stance` is filled by the claim
step, not here. Spoken opinion is context; numbers in it are never evidence until a deterministic tool confirms them.
"""

from __future__ import annotations

import csv
import difflib
import itertools
import json
import logging
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bistharness import __version__
from bistharness.core.config import Settings
from bistharness.core.errors import DataNotFoundError, SnapshotIntegrityError
from bistharness.core.hashing import file_sha256, sha256_hex
from bistharness.data import db
from bistharness.data.ingest import manifest as mf
from bistharness.data.ingest.news import TAGS_FILE, Tagger, tr_lower

log = logging.getLogger(__name__)

SPEECH_SOURCE = "speech"
VIDEOS_FILE = "videos.csv"
TRANSCRIPT_DIR = "transcripts"
SEGMENT_SECONDS = 60.0
LAST_CUE_SECONDS = 5.0  # duration assumed for the last cue when the video length is unknown
MIN_ANCHOR_WORDS = 3  # matching runs shorter than this do not anchor the caption span (common words)
VIDEO_COLUMNS = (
    "source_id",
    "url",
    "channel",
    "speaker",
    "title",
    "language",
    "published_at",
    "duration_s",
    "transcript_kind",
    "quality_from",
    "official_text_url",
    "selection_reason",
)

_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})"
_TS_LINE = re.compile(rf"^{_TS}$")
_TS_INLINE = re.compile(rf"^{_TS}\s+(\S.*)$")
_UNIT = r"(?:saat|dakika|saniye|hours?|minutes?|seconds?)"
_DURATION_LABEL = re.compile(rf"^\d+\s+{_UNIT}(?:,?\s+\d+\s+{_UNIT})*$", re.IGNORECASE)  # screen-reader labels


# --------------------------------------------------------------------------- transcript parsing
@dataclass(frozen=True)
class Cue:
    start: float
    text: str


def _seconds(h: str | None, m: str, s: str) -> float:
    return float(int(h or 0) * 3600 + int(m) * 60 + int(s))


def parse_transcript(text: str) -> list[Cue]:
    """YouTube transcript panel text -> cues. Accepts `0:05` on its own line followed by text lines, or `0:05 text`
    on one line; skips screen-reader duration labels ("5 saniye", "1 dakika, 2 saniye") and anything before the
    first timestamp (panel header). Timestamps must not go backwards (a pasting error)."""
    cues: list[Cue] = []
    start: float | None = None
    buf: list[str] = []

    def flush() -> None:
        if start is not None and buf:
            cues.append(Cue(start, " ".join(buf)))

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _TS_LINE.match(line) or _TS_INLINE.match(line)
        if m:
            flush()
            start, buf = _seconds(m.group(1), m.group(2), m.group(3)), []
            if m.re is _TS_INLINE:
                buf.append(m.group(4))
            continue
        if _DURATION_LABEL.match(line) or start is None:
            continue
        buf.append(line)
    flush()
    for a, b in itertools.pairwise(cues):
        if b.start < a.start:
            raise ValueError(f"transcript timestamps go backwards at {b.start:.0f}s (pasted twice or out of order?)")
    return cues


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


def segment_cues(cues: list[Cue], duration: float | None, window: float = SEGMENT_SECONDS) -> list[Segment]:
    groups: list[list[Cue]] = []
    for c in cues:
        if not groups or c.start - groups[-1][0].start >= window:
            groups.append([c])
        else:
            groups[-1].append(c)
    out: list[Segment] = []
    for i, g in enumerate(groups):
        end = groups[i + 1][0].start if i + 1 < len(groups) else max(duration or 0.0, g[-1].start + LAST_CUE_SECONDS)
        out.append(Segment(g[0].start, end, " ".join(c.text for c in g)))
    return out


# --------------------------------------------------------------------------- caption quality
def words(text: str) -> list[str]:
    return re.findall(r"\w+", tr_lower(text).replace("%", " yüzde "))


def aligned_wer(official: str, captions: str) -> float:
    """Word error rate of the captions against the official text, over the caption span the official text covers
    (a speech text usually omits the Q&A that the video and its captions include). Edits are counted from difflib's
    alignment: replace = max(len), delete / insert = len. Returns 1.0 when nothing aligns."""
    ref, hyp = words(official), words(captions)
    if not ref:
        raise ValueError("official text is empty")
    blocks = [b for b in difflib.SequenceMatcher(None, ref, hyp, autojunk=False).get_matching_blocks() if b.size]
    anchors = [b for b in blocks if b.size >= min(MIN_ANCHOR_WORDS, len(ref))]
    if not anchors:
        return 1.0
    first, last = anchors[0], anchors[-1]
    lo, hi = first.b, last.b + last.size
    # short matches just outside the anchors belong to the speech when their caption gap fits the official gap
    for b in reversed([b for b in blocks if b.a < first.a]):
        if lo - (b.b + b.size) <= 2 * (first.a - (b.a + b.size)) + 5:
            lo, first = b.b, b
    for b in [b for b in blocks if b.a >= last.a + last.size]:
        if b.b - hi <= 2 * (b.a - (last.a + last.size)) + 5:
            hi, last = b.b + b.size, b
    span = hyp[lo:hi]
    edits = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ref, span, autojunk=False).get_opcodes():
        if op == "replace":
            edits += max(i2 - i1, j2 - j1)
        elif op == "delete":
            edits += i2 - i1
        elif op == "insert":
            edits += j2 - j1
    return round(min(1.0, edits / len(ref)), 4)


# --------------------------------------------------------------------------- video list + snapshot
@dataclass(frozen=True)
class Video:
    source_id: str
    url: str
    channel: str
    speaker: str
    title: str
    language: str
    published_at: str
    duration_s: float | None
    transcript_kind: str
    quality_from: str
    official_text_url: str
    selection_reason: str


def read_videos(path: Path) -> list[Video]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or tuple(rows[0]) != VIDEO_COLUMNS:
        raise ValueError(f"{path}: columns must be {', '.join(VIDEO_COLUMNS)}")
    out: list[Video] = []
    for r in rows:
        datetime.strptime(r["published_at"], "%Y-%m-%d %H:%M:%S")  # Europe/Istanbul local, like news_events
        out.append(
            Video(
                **{k: (r[k] or "").strip() for k in VIDEO_COLUMNS if k != "duration_s"},
                duration_s=float(r["duration_s"]) if r["duration_s"] else None,
            )
        )
    ids = [v.source_id for v in out]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate source_id")
    return out


def _inputs(manual: Path) -> dict[str, Path]:
    """Published-path -> source file for everything the speech snapshot freezes (non-empty transcripts only)."""
    out = {VIDEOS_FILE: manual / VIDEOS_FILE}
    tdir = manual / TRANSCRIPT_DIR
    if tdir.exists():
        for p in sorted(tdir.glob("*.txt")):
            if p.read_text(encoding="utf-8").strip():
                out[f"{TRANSCRIPT_DIR}/{p.name}"] = p
    return out


def prepare_speech_snapshot(settings: Settings, snapshot: str) -> dict[str, object]:
    """Copies videos.csv + the non-empty transcripts into data/raw/speech/<snapshot>/ with a sha256 manifest.
    An existing snapshot is verified AND compared with the current inputs: a transcript added or edited after
    freezing needs a new snapshot name (results are never silently computed from different text)."""
    manual = settings.path("manual")
    if not (manual / VIDEOS_FILE).exists():
        raise DataNotFoundError(f"video list not found: {manual / VIDEOS_FILE}")
    inputs = _inputs(manual)
    dest = settings.raw_dir / SPEECH_SOURCE / snapshot
    if (dest / mf.MANIFEST_NAME).exists():
        m = mf.verify_manifest(dest)
        current = {rel: file_sha256(p) for rel, p in inputs.items()}
        if current != m["files"]:
            changed = sorted(set(current.items()) ^ set(m["files"].items()))
            raise SnapshotIntegrityError(
                f"{dest}: inputs changed since this snapshot was frozen ({', '.join(sorted({c[0] for c in changed}))});"
                " use a new --snapshot name"
            )
        return m
    for rel, src in inputs.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest / rel)
    log.info("froze %d speech input files into %s", len(inputs), dest)
    return mf.write_manifest(dest, source=SPEECH_SOURCE, params={"segment_seconds": SEGMENT_SECONDS})


# --------------------------------------------------------------------------- ingest
@dataclass
class VideoReport:
    source_id: str
    segments: int = 0
    tickers: list[str] = field(default_factory=list)
    quality: float | None = None
    wer: float | None = None
    skipped: str | None = None


@dataclass
class SpeechSummary:
    ingest_id: str
    videos: list[VideoReport]

    @property
    def segments(self) -> int:
        return sum(v.segments for v in self.videos)


def build_segments(
    snap: Path, videos: list[Video], tagger: Tagger, cutoff: str
) -> tuple[list[tuple[object, ...]], list[VideoReport]]:
    reports: dict[str, VideoReport] = {v.source_id: VideoReport(v.source_id) for v in videos}
    parsed: dict[str, list[Cue]] = {}
    for v in videos:
        rep = reports[v.source_id]
        path = snap / TRANSCRIPT_DIR / f"{v.source_id}.txt"
        if v.published_at >= cutoff:
            rep.skipped = "PUBLISHED_AFTER_SNAPSHOT"
        elif not path.exists():
            rep.skipped = "TRANSCRIPT_MISSING"
        else:
            parsed[v.source_id] = parse_transcript(path.read_text(encoding="utf-8"))
            if not parsed[v.source_id]:
                rep.skipped = "TRANSCRIPT_WITHOUT_TIMESTAMPS"
                del parsed[v.source_id]
    for v in videos:  # quality measured on official texts first ...
        official = snap / TRANSCRIPT_DIR / f"{v.source_id}.official.txt"
        if v.quality_from == "self" and v.source_id in parsed and official.exists():
            rep = reports[v.source_id]
            rep.wer = aligned_wer(official.read_text(encoding="utf-8"), " ".join(c.text for c in parsed[v.source_id]))
            rep.quality = round(1.0 - rep.wer, 4)
    for v in videos:  # ... then borrowed by the videos that use the same caption system and language
        if v.quality_from not in ("", "self") and v.quality_from in reports:
            reports[v.source_id].quality = reports[v.quality_from].quality
    rows: list[tuple[object, ...]] = []
    for v in videos:
        if v.source_id not in parsed:
            continue
        rep = reports[v.source_id]
        named: Counter[str] = Counter()
        for s in segment_cues(parsed[v.source_id], v.duration_s):
            tick = [t for t in tagger.universe if tagger.mentions(t, s.text) > 0]
            named.update(tick)
            topics = sorted(tick) + tagger.topics_of("", s.text, lead_chars=len(s.text))
            rows.append(
                (
                    v.source_id,
                    s.start,
                    s.end,
                    v.published_at,
                    v.url,
                    v.speaker,
                    v.channel,
                    s.text,
                    json.dumps(topics, ensure_ascii=False),
                    None,
                    rep.quality,
                )
            )
            rep.segments += 1
        rep.tickers = sorted(named)
    return rows, list(reports.values())


def run(settings: Settings, snapshot: str, tagger: Tagger | None = None) -> SpeechSummary:
    datetime.strptime(snapshot, "%Y-%m-%d")  # snapshot = first day NOT included -> must be a date
    started = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    manifest = prepare_speech_snapshot(settings, snapshot)
    snap = settings.raw_dir / SPEECH_SOURCE / snapshot
    tags_path = settings.root / TAGS_FILE
    tagger = tagger or Tagger.load(tags_path)
    rows, reports = build_segments(snap, read_videos(snap / VIDEOS_FILE), tagger, f"{snapshot} 00:00:00")
    version = sha256_hex([manifest["content_sha256"], file_sha256(tags_path) if tags_path.exists() else ""])
    ingest_id = f"speech-{snapshot}-{version[:10]}"
    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        conn.execute("DELETE FROM speech_segments")
        conn.executemany(
            "INSERT INTO speech_segments (source_id, segment_start, segment_end, published_at, url, speaker, channel, "
            "text, topics, stance, quality, ingest_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(*r, ingest_id) for r in rows],
        )
        conn.execute(
            "INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ingest_id,
                SPEECH_SOURCE,
                snapshot,
                version,
                len(rows),
                "{}",
                started,
                datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                __version__,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return SpeechSummary(ingest_id, reports)


__all__ = [
    "Cue",
    "Segment",
    "SpeechSummary",
    "Video",
    "aligned_wer",
    "parse_transcript",
    "prepare_speech_snapshot",
    "read_videos",
    "run",
    "segment_cues",
]
