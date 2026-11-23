"""Deterministic hashing: canonical JSON for tool inputs/outputs and sha256 for frozen files."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _default(obj: Any) -> Any:
    if isinstance(obj, (datetime, pd.Timestamp)):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return None if math.isnan(float(obj)) else float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, Path):
        return obj.as_posix()
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def canonical_json(obj: Any) -> str:
    """JSON with sorted keys and no whitespace: equal objects always give equal strings."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default, allow_nan=False)


def sha256_hex(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()
