"""Trading calendar truncated at as_of, and the forward-window completeness rule (CLAUDE.md §2).

An event on trading day t has a complete h-day forward window at as_of iff at least h trading days
after t are <= as_of. Incomplete events are never silently dropped: they are returned as ExcludedEvent.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from bistharness.core.schemas import ExcludedEvent


@dataclass(frozen=True)
class ForwardWindow:
    event_date: date
    horizon: int
    complete: bool
    trading_days_available: int
    end_date: date | None  # the t+h trading day if complete


class TradingCalendar:
    """Sorted, de-duplicated trading days known at as_of (days after as_of are discarded on construction)."""

    def __init__(self, days: Iterable[date], as_of: date) -> None:
        self.as_of = as_of
        self._days: list[date] = sorted({d for d in days if d <= as_of})

    def __len__(self) -> int:
        return len(self._days)

    @property
    def days(self) -> Sequence[date]:
        return tuple(self._days)

    @property
    def last(self) -> date | None:
        return self._days[-1] if self._days else None

    def is_trading_day(self, d: date) -> bool:
        i = bisect_left(self._days, d)
        return i < len(self._days) and self._days[i] == d

    def days_after(self, d: date) -> int:
        """Number of known trading days strictly after d (and <= as_of)."""
        return len(self._days) - bisect_right(self._days, d)

    def nth_after(self, d: date, n: int) -> date | None:
        """The n-th trading day strictly after d, or None if it is not known at as_of."""
        if n < 1:
            raise ValueError("n must be >= 1")
        i = bisect_right(self._days, d) + n - 1
        return self._days[i] if i < len(self._days) else None

    def window(self, event_date: date, horizon: int) -> ForwardWindow:
        if horizon < 1:
            raise ValueError("horizon must be >= 1")
        if event_date > self.as_of:
            # An event after as_of cannot exist in a point-in-time analysis.
            return ForwardWindow(event_date, horizon, False, 0, None)
        available = self.days_after(event_date)
        end = self.nth_after(event_date, horizon)
        return ForwardWindow(event_date, horizon, end is not None, min(available, horizon), end)

    def split_complete(
        self,
        event_dates: Iterable[date],
        horizons: Sequence[int],
        *,
        event_type: str | None = None,
        ticker: str | None = None,
    ) -> tuple[dict[int, list[date]], list[ExcludedEvent]]:
        """For each horizon, the events with a complete window, plus the explicit exclusion list."""
        complete: dict[int, list[date]] = {h: [] for h in horizons}
        excluded: list[ExcludedEvent] = []
        for ev in sorted(set(event_dates)):
            for h in horizons:
                w = self.window(ev, h)
                if w.complete:
                    complete[h].append(ev)
                else:
                    excluded.append(
                        ExcludedEvent(
                            event_date=ev,
                            horizon=h,
                            trading_days_available=w.trading_days_available,
                            event_type=event_type,
                            ticker=ticker,
                        )
                    )
        return complete, excluded
