"""Draw a reproducible sample from local speech reviews and score human labels."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from bistharness.analytics.stats import wilson_interval
from bistharness.core.config import load_settings
from bistharness.core.hashing import sha256_hex
from bistharness.core.speech_claims import ReviewRecord


def sample_reviews(folder: Path, size: int, seed: int) -> list[ReviewRecord]:
    items: dict[str, ReviewRecord] = {}
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = ReviewRecord.model_validate_json(line)
                if item.claim_id != item.expected_id or item.claim_id in items or item.source_id != path.stem:
                    raise ValueError(f"Invalid review identity in {path.name}")
                items[item.claim_id] = item
    return sorted(items.values(), key=lambda item: sha256_hex([seed, item.claim_id]))[:size]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--list", action="store_true", help="List the sampled source, time, review ID and quote.")
    args = parser.parse_args(argv)
    if args.size < 1:
        parser.error("--size must be positive")
    sample = sample_reviews(load_settings().path("manual") / "claims", args.size, args.seed)
    if not sample:
        parser.error("No local speech claim proposals")
    if args.list:
        for item in sample:
            print(f"{item.source_id} @{item.segment_start:.0f}s {item.claim_id} · {item.claim.quote}")
    counts = Counter(item.audit for item in sample)
    print(
        f"Örnek: {len(sample)} · doğru: {counts['correct']} · kısmen: {counts['partial']} "
        f"· yanlış: {counts['incorrect']} · bekliyor: {counts[None]}"
    )
    if counts[None]:
        return 1
    n = len(sample)
    for label, hits in (("Katı", counts["correct"]), ("Geniş", counts["correct"] + counts["partial"])):
        interval = wilson_interval(hits, n)
        if interval is not None:
            print(f"{label} kesinlik {hits / n:.1%} · %95 Wilson aralığı {interval[0]:.1%}–{interval[1]:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
