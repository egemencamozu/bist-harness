"""News metadata ingest: Bloomberg HT archive (FinTreX haber-scrapper) -> news_events (contextual evidence only).

Source: `paths.external.news_bloomberght/bloomberg_ht_6_YYYY-MM.json` = {"messages": [{published_at, articles:
{url: {title, text, page_published_at, page_modified_at, fetched_at}}}]}. Tagging: `config/news.yaml`.

Point-in-time rule (found in the 2026-11-21 profile): the archived text is the version fetched in 2026; for ~35 % of
articles it was last modified after first publication (message `published_at` == `page_modified_at`). Tags derived
from that text are therefore known only from the LAST of (page_published_at, page_modified_at, published_at):
`news_events.published_at` = that conservative knowledge time; `first_published_at` keeps the original time.
Timestamps are converted from UTC to Europe/Istanbul local (UTC+3, no DST since 2016).

Only metadata reaches the DB (title, url, tickers, topics, event_type) — never article text. News is context; it never
replaces numeric data, and numeric claims inside news must be verified by deterministic tools (CLAUDE.md §1, §11).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import re
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from bistharness import __version__
from bistharness.core.config import Settings
from bistharness.core.errors import DataNotFoundError
from bistharness.core.hashing import file_sha256, sha256_hex
from bistharness.data import db
from bistharness.data.ingest import manifest as mf

log = logging.getLogger(__name__)

NEWS_SOURCE = "news_bloomberght"
SNAPSHOT_FILE = "articles.jsonl.gz"
TAGS_FILE = Path("config") / "news.yaml"
FILE_GLOB = "bloomberg_ht_6_*.json"
ISTANBUL_OFFSET = timedelta(hours=3)
_TR_UPPER = str.maketrans({"İ": "i", "I": "ı"})


def tr_lower(text: str) -> str:
    return text.translate(_TR_UPPER).lower()


def to_istanbul(ts: str) -> str:
    """ISO timestamp (any offset) -> 'YYYY-MM-DD HH:MM:SS' Europe/Istanbul local."""
    d = datetime.fromisoformat(ts)
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return (d.astimezone(UTC) + ISTANBUL_OFFSET).strftime("%Y-%m-%d %H:%M:%S")


def _phrase_regex(phrase: str) -> str:
    star = phrase.endswith("*")
    core = re.escape(tr_lower(phrase.rstrip("*")))
    return rf"(?<!\w){core}\w*" if star else rf"(?<!\w){core}(?!\w)"


@dataclass(frozen=True)
class _Matcher:
    """One ticker's patterns. `cores` are literal substrings every match must contain: when none occurs in the text
    the regex cannot match and is skipped (pure speed-up, identical results)."""

    rx: re.Pattern[str]
    cores: tuple[str, ...]

    def count(self, text: str) -> int:
        return len(self.rx.findall(text)) if any(c in text for c in self.cores) else 0


@dataclass(frozen=True)
class Tagger:
    names: dict[str, _Matcher]  # ticker -> case-insensitive aliases (run on tr_lower text)
    exact: dict[str, _Matcher]  # ticker -> case-sensitive tokens incl. the ticker code (run on the original text)
    codes: dict[str, _Matcher]  # ticker -> its code only (absent when `code: false`: the code is an everyday word)
    excludes: dict[str, re.Pattern[str]]  # ticker -> phrases blanked out before its aliases are matched
    topics: dict[str, _Matcher]  # ordered: event_type priority (run on tr_lower lead)
    min_body_mentions: int
    max_body_tickers: int
    roundup: re.Pattern[str]

    @staticmethod
    def _phrases(phrases: list[str]) -> _Matcher:
        return _Matcher(
            re.compile("|".join(_phrase_regex(p) for p in phrases)), tuple(tr_lower(p.rstrip("*")) for p in phrases)
        )

    @staticmethod
    def _tokens(tokens: list[str]) -> _Matcher:
        return _Matcher(re.compile("|".join(rf"(?<!\w){re.escape(t)}(?!\w)" for t in tokens)), tuple(tokens))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Tagger:
        specs: dict[str, dict[str, Any]] = raw["tickers"]
        names = {t: cls._phrases(spec["names"]) for t, spec in specs.items() if spec.get("names")}
        exact = {
            t: cls._tokens([*([t] if spec.get("code", True) else []), *spec.get("exact", [])])
            for t, spec in specs.items()
            if spec.get("code", True) or spec.get("exact")
        }
        codes = {t: cls._tokens([t]) for t, spec in specs.items() if spec.get("code", True)}
        excludes = {
            t: re.compile("|".join(_phrase_regex(p) for p in spec["exclude"]))
            for t, spec in specs.items()
            if spec.get("exclude")
        }
        topics = {k: cls._phrases(v) for k, v in raw["topics"].items()}
        roundup = re.compile("|".join(re.escape(tr_lower(p)) for p in raw.get("roundup_title_patterns", [])) or "$^")
        return cls(
            names,
            exact,
            codes,
            excludes,
            topics,
            int(raw.get("min_body_mentions", 2)),
            int(raw.get("max_body_tickers", 4)),
            roundup,
        )

    @classmethod
    def load(cls, path: Path) -> Tagger:
        with path.open("r", encoding="utf-8") as fh:
            return cls.from_dict(yaml.safe_load(fh))

    @property
    def universe(self) -> list[str]:
        return sorted(set(self.names) | set(self.exact))

    def _mentions(self, ticker: str, text: str, low: str) -> int:
        n = self.exact[ticker].count(text) if ticker in self.exact else 0
        if ticker in self.names:
            ex = self.excludes.get(ticker)
            n += self.names[ticker].count(ex.sub(" ", low) if ex else low)
        return n

    def mentions(self, ticker: str, text: str) -> int:
        """Name / exact-token mentions of `ticker` in free text (exclusions applied)."""
        return self._mentions(ticker, text, tr_lower(text))

    def in_title(self, ticker: str, title: str) -> bool:
        return self._mentions(ticker, title, tr_lower(title)) > 0

    def _body_hit(self, t: str, body: str, low_body: str) -> bool:
        return (t in self.codes and self.codes[t].count(body) > 0) or self._mentions(
            t, body, low_body
        ) >= self.min_body_mentions

    def tickers(self, title: str, body: str, quoted: Mapping[str, Collection[str]] | None = None) -> list[str]:
        """Tickers of one article. `quoted`: ticker -> Turkish-lowercased titles of OTHER articles naming it in their
        title; such a headline copied verbatim into this body is a related-news box / weekly digest link (the archive
        text of ~2 % of pages carries one), so it is blanked out before the body is matched."""
        low_title, low_body = tr_lower(title), tr_lower(body)
        roundup = bool(self.roundup.search(low_title))
        in_title: set[str] = set()
        body_only: set[str] = set()
        for t in self.universe:
            if self._mentions(t, title, low_title) > 0:
                in_title.add(t)
            elif not roundup and self._body_hit(t, body, low_body):
                if quoted and quoted.get(t):
                    b, lb = _blank_quoted(body, low_body, quoted[t], own=low_title)
                    if not self._body_hit(t, b, lb):
                        continue
                body_only.add(t)
        if len(body_only) > self.max_body_tickers:  # market recap listing many codes: not news about each of them
            body_only = set()
        return sorted(in_title | body_only)

    def topics_of(self, title: str, body: str, lead_chars: int = 600) -> list[str]:
        low = tr_lower(f"{title}\n{body[:lead_chars]}")
        return [k for k, m in self.topics.items() if m.count(low) > 0]


QUOTED_TITLE_MIN_CHARS = 25  # shorter headlines ("Aselsan'dan sözleşme") are too generic to treat as a copied link


def _blank_quoted(body: str, low_body: str, titles: Collection[str], *, own: str) -> tuple[str, str]:
    """Blank every verbatim occurrence of another article's (lowercased) title in the body (both spellings)."""
    if len(body) != len(low_body):  # tr_lower changed the length (rare Unicode): keep the body unchanged
        return body, low_body
    spans: list[tuple[int, int]] = []
    for t in titles:
        if len(t) < QUOTED_TITLE_MIN_CHARS or t == own:
            continue
        i = low_body.find(t)
        while i >= 0:
            spans.append((i, i + len(t)))
            i = low_body.find(t, i + len(t))
    if not spans:
        return body, low_body
    raw, low = list(body), list(low_body)
    for i, j in spans:
        raw[i:j] = " " * (j - i)
        low[i:j] = " " * (j - i)
    return "".join(raw), "".join(low)


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    text: str
    first_published_at: str  # Istanbul local
    knowledge_at: str  # Istanbul local, conservative (see module docstring)


def iter_articles(files: Iterable[Path]) -> Iterator[Article]:
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for msg in data.get("messages", []):
            for url, art in (msg.get("articles") or {}).items():
                stamps = [
                    s for s in (art.get("page_published_at"), art.get("page_modified_at"), msg.get("published_at")) if s
                ]
                if not stamps or not art.get("title"):
                    continue
                local = sorted(to_istanbul(s) for s in stamps)
                first = to_istanbul(art["page_published_at"]) if art.get("page_published_at") else local[0]
                yield Article(url, str(art["title"]).strip(), str(art.get("text") or ""), first, local[-1])


def event_id(url: str) -> str:
    return "bht:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def quoted_titles(articles: Sequence[Article], tagger: Tagger) -> dict[str, set[str]]:
    """ticker -> lowercased titles of the articles that name it in their title (see Tagger.tickers)."""
    out: dict[str, set[str]] = {}
    for a in articles:
        for t in tagger.universe:
            if tagger.in_title(t, a.title):
                out.setdefault(t, set()).add(tr_lower(a.title.strip()))
    return out


def tag_articles(articles: Iterable[Article], tagger: Tagger) -> pd.DataFrame:
    arts = list(articles)
    quoted = quoted_titles(arts, tagger)
    rows = []
    for a in arts:
        topics = tagger.topics_of(a.title, a.text)
        rows.append(
            {
                "event_id": event_id(a.url),
                "published_at": a.knowledge_at,
                "first_published_at": a.first_published_at,
                "source": "bloomberght",
                "title": a.title,
                "url": a.url,
                "tickers": json.dumps(tagger.tickers(a.title, a.text, quoted)),
                "topics": json.dumps(topics),
                "event_type": topics[0] if topics else "other",
            }
        )
    return pd.DataFrame(rows).sort_values(["published_at", "event_id"]).reset_index(drop=True)


# --------------------------------------------------------------------------- snapshot + ingest
def prepare_news_snapshot(settings: Settings, snapshot: str) -> dict[str, Any]:
    dest = settings.raw_dir / NEWS_SOURCE / snapshot
    if (dest / mf.MANIFEST_NAME).exists():
        return mf.verify_manifest(dest)
    src = settings.path("external", "news_bloomberght")
    files = sorted(p for p in src.glob(FILE_GLOB) if p.suffix == ".json")
    if not files:
        raise DataNotFoundError(f"no Bloomberg HT archive files ({FILE_GLOB}) under {src}")
    cutoff = f"{snapshot} 00:00:00"
    arts = sorted((a for a in iter_articles(files) if a.knowledge_at < cutoff), key=lambda a: a.url)
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / SNAPSHOT_FILE).open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8", newline="\n")
        for a in arts:
            text.write(json.dumps(a.__dict__, ensure_ascii=False, sort_keys=True) + "\n")
        text.flush()
        text.detach()
    params = {
        "source_files": {f.name: {"bytes": f.stat().st_size, "sha256": file_sha256(f)} for f in files},
        "articles": len(arts),
        "knowledge_time_rule": "max(page_published_at, page_modified_at, published_at) in Europe/Istanbul",
    }
    log.info("froze %d Bloomberg HT articles into %s", len(arts), dest)
    return mf.write_manifest(dest, source=NEWS_SOURCE, params=params)


def load_snapshot(settings: Settings, snapshot: str) -> list[Article]:
    with gzip.open(settings.raw_dir / NEWS_SOURCE / snapshot / SNAPSHOT_FILE, "rt", encoding="utf-8") as fh:
        return [Article(**json.loads(line)) for line in fh]


@dataclass
class NewsSummary:
    ingest_id: str
    articles: int
    with_tickers: int
    first: str
    last: str
    per_ticker: dict[str, int]
    per_event_type: dict[str, int]


def run(settings: Settings, snapshot: str) -> NewsSummary:
    started = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    manifest = prepare_news_snapshot(settings, snapshot)
    tags_path = settings.root / TAGS_FILE
    events = tag_articles(load_snapshot(settings, snapshot), Tagger.load(tags_path))
    version = sha256_hex([manifest["content_sha256"], file_sha256(tags_path)])
    ingest_id = f"news-{snapshot}-{version[:10]}"
    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        conn.execute("DELETE FROM news_events")
        conn.executemany(
            "INSERT INTO news_events (event_id, published_at, first_published_at, source, title, url, tickers, topics, "
            "event_type, ingest_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(*r, ingest_id) for r in events.itertuples(index=False)],
        )
        conn.execute(
            "INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ingest_id,
                "news",
                snapshot,
                version,
                len(events),
                "{}",
                started,
                datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                __version__,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    tick = Counter(t for ts in events["tickers"] for t in json.loads(ts))
    return NewsSummary(
        ingest_id=ingest_id,
        articles=len(events),
        with_tickers=int((events["tickers"] != "[]").sum()),
        first=str(events["published_at"].min()),
        last=str(events["published_at"].max()),
        per_ticker=dict(sorted(tick.items())),
        per_event_type=events["event_type"].value_counts().to_dict(),
    )


__all__ = [
    "Article",
    "NewsSummary",
    "Tagger",
    "event_id",
    "iter_articles",
    "quoted_titles",
    "run",
    "tag_articles",
    "to_istanbul",
    "tr_lower",
]
