"""Turn explicitly reviewed, frozen proposals into publication-dated rows."""

from __future__ import annotations

from pathlib import Path

from bistharness.core.errors import SnapshotIntegrityError
from bistharness.core.hashing import canonical_json
from bistharness.core.speech_claims import ClaimSegment, ReviewRecord, source_numbers


def approved_rows(
    folder: Path, segments: dict[tuple[str, float], ClaimSegment], ingest_id: str
) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    ids: set[str] = set()
    runs: dict[tuple[str, float], str] = {}
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            review = ReviewRecord.model_validate_json(line)
            if review.reviewed is not True:
                continue
            key = (review.source_id, review.segment_start)
            segment = segments.get(key)
            claim = review.claim
            if (
                path.stem != review.source_id
                or segment is None
                or segment.digest != review.segment_sha256
                or review.claim_id != review.expected_id
                or review.claim_id in ids
                or claim.quote not in segment.text
                or review.audit in {"partial", "incorrect"}
                or runs.setdefault(key, review.extraction_sha256) != review.extraction_sha256
            ):
                raise SnapshotIntegrityError(f"Stale, conflicting or invalid approved review in {path.name}")
            ids.add(review.claim_id)
            rows.append(
                (
                    review.claim_id,
                    review.source_id,
                    review.segment_start,
                    segment.published_at,
                    segment.digest,
                    review.extraction_sha256,
                    claim.subject,
                    claim.claim_type,
                    claim.quote,
                    canonical_json(source_numbers(claim.quote)),
                    claim.metric,
                    claim.direction,
                    claim.horizon_days,
                    claim.stance,
                    claim.certainty,
                    review.review_note,
                    ingest_id,
                )
            )
    return rows
