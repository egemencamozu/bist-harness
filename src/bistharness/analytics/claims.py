"""Pure checks over normalized observations and caller-selected trading windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from bistharness.core.calendar import TradingCalendar


class Verdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    PARTIAL = "PARTIAL"
    NOT_VERIFIABLE = "NOT_VERIFIABLE"
    FORWARD_WINDOW_INCOMPLETE = "FORWARD_WINDOW_INCOMPLETE"


def compare_observation(observed: Decimal | None, lower: Decimal, upper: Decimal) -> Verdict:
    """Compare a value to explicitly supplied inclusive bounds in the same unit."""
    if not lower.is_finite() or not upper.is_finite() or lower > upper:
        raise ValueError("Expected ordered finite claim bounds")
    if observed is None or not observed.is_finite():
        return Verdict.NOT_VERIFIABLE
    return Verdict.SUPPORTED if lower <= observed <= upper else Verdict.CONTRADICTED


@dataclass(frozen=True)
class ForecastWindow:
    end: date | None
    failure: Verdict | None = None


def forecast_window(calendar: TradingCalendar, anchor: date, as_of: date, sessions: int) -> ForecastWindow:
    """Resolve an already chosen trading-session anchor using only dates visible at as_of."""
    if sessions < 1:
        raise ValueError("Forecast horizon must be positive")
    if anchor > as_of:
        return ForecastWindow(None, Verdict.NOT_VERIFIABLE)
    if not calendar.is_trading_day(anchor):
        return ForecastWindow(None, Verdict.NOT_VERIFIABLE)
    end = calendar.nth_after(anchor, sessions)
    if end is None or end > as_of:
        return ForecastWindow(None, Verdict.FORWARD_WINDOW_INCOMPLETE)
    return ForecastWindow(end)
