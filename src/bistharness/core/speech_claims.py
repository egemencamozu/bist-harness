"""Shared speech claim records and source identity."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from bistharness.core.formatting import typed_numbers_in
from bistharness.core.hashing import sha256_hex


class ClaimProposal(BaseModel):
    """Model output. Numeric metadata is derived separately from the source quote."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    subject: Annotated[str, Field(min_length=1, max_length=48)]
    claim_type: Literal[
        "fundamental_value",
        "price_move_past",
        "price_move_forecast",
        "sector_relative_forecast",
        "volume_flow",
        "foreign_or_broker_flow",
        "macro_value",
        "opinion",
    ]
    quote: Annotated[str, Field(min_length=3, max_length=320)]
    metric: Annotated[str, Field(pattern=r"^[a-z_]{1,48}$")] | None
    direction: Literal["up", "down", "none"]
    horizon_days: Annotated[int, Field(ge=1, le=365)] | None
    stance: Literal["positive", "negative", "neutral"]
    certainty: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class ClaimSegment:
    source_id: str
    start: float
    end: float
    published_at: str
    text: str
    topics: tuple[str, ...]

    @classmethod
    def from_values(
        cls, source_id: str, start: float, end: float, published_at: str, text: str, topics_json: str
    ) -> ClaimSegment:
        return cls(source_id, float(start), float(end), published_at, text, tuple(json.loads(topics_json)))

    @property
    def digest(self) -> str:
        return sha256_hex([self.source_id, self.start, self.end, self.published_at, self.text, self.topics])


class ReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    claim_id: str
    source_id: str
    segment_start: float
    segment_sha256: str
    extraction_sha256: str
    claim: ClaimProposal
    reviewed: bool | None = None
    review_note: str = Field(default="", max_length=1000)
    audit: Literal["correct", "partial", "incorrect"] | None = None

    @property
    def expected_id(self) -> str:
        return sha256_hex([self.segment_sha256, self.extraction_sha256, self.claim.model_dump()])


def source_numbers(quote: str) -> list[tuple[str, float]]:
    """Preserve quoted numbers and their percent distinction."""
    normalized = re.sub(r"(?i)\byüzde\s+([+-]?\d)", r"%\1", quote)
    normalized = re.sub(r"(?i)(?<![\w%])([+-]?\d+(?:[.,]\d+)?)\s*(?:%|percent\b)", r"%\1", normalized)
    return typed_numbers_in(normalized)
