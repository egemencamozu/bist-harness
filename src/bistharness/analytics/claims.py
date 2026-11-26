"""Pure checks over normalized observations and caller-selected trading windows."""

from __future__ import annotations

import re
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


_PERCENT = re.compile(
    r"(?i)(?:%|\byüzde\s+)\s*([+-]?\d+(?:[.,]\d{1,2})?)(?![\d]|[.,]\d)"
    r"|(?<![\d.,%])([+-]?\d+(?:[.,]\d{1,2})?)\s*(?:%|\bpercent\b)"
)


def quoted_percent_bounds(quote: str) -> tuple[Decimal, Decimal] | None:
    """Use half the last quoted place for one explicit percentage."""
    quote = re.sub(r"([+-])\s*%\s*(?=\d)", r"%\1", quote.replace("−", "-"))
    numbers = [a or b for a, b in _PERCENT.findall(quote)]
    if len(numbers) != 1:
        return None
    value = Decimal(numbers[0].replace(",", "."))
    tolerance = Decimal("0.5").scaleb(-len(numbers[0].replace(",", ".").partition(".")[2]))
    return value - tolerance, value + tolerance


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
