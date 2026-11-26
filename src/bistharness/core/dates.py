"""Date parsing/formatting conventions.

Storage convention (SQLite):
- dates:      'YYYY-MM-DD'
- datetimes:  'YYYY-MM-DD HH:MM:SS' in Europe/Istanbul local time (fixed UTC+3 since 2016, no DST),
  so lexicographic comparison equals chronological comparison.
`as_of` is interpreted as end of that day (after the close): the as_of close is known.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from bistharness.core.errors import AsOfRequiredError

DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


def to_date(value: Any, *, name: str = "date") -> date:
    if value is None:
        raise AsOfRequiredError(f"{name} is required") if name == "as_of_date" else ValueError(f"{name} is required")
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise ValueError(f"{name}: invalid ISO date {value!r}") from exc
    raise TypeError(f"{name}: unsupported type {type(value).__name__}")


def require_as_of(value: Any) -> date:
    """Validate an as_of_date. Raises AsOfRequiredError for None/empty."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise AsOfRequiredError("as_of_date is mandatory for every data access")
    return to_date(value, name="as_of_date")


def as_of_end_of_day(as_of: date) -> str:
    """Upper bound for datetime knowledge columns: everything published on as_of counts as known."""
    return f"{as_of.strftime(DATE_FMT)} 23:59:59"


def knowledge_bound(as_of: date, cutoff: datetime | None) -> str:
    """Clamp a local Istanbul timestamp to the mandatory analysis date."""
    end_of_day = as_of_end_of_day(as_of)
    if cutoff is None:
        return end_of_day
    if cutoff.tzinfo is not None:
        raise ValueError("knowledge_cutoff must be a naive Istanbul-local datetime")
    return min(end_of_day, cutoff.strftime(DATETIME_FMT))


def fmt_date(d: date) -> str:
    return d.strftime(DATE_FMT)
