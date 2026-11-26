from datetime import date
from decimal import Decimal

import pytest

from bistharness.analytics.claims import ForecastWindow, Verdict, compare_observation, forecast_window
from bistharness.core.calendar import TradingCalendar


def test_inclusive_bounds_and_missing_observations() -> None:
    low, high = Decimal("11.5"), Decimal("12.5")
    assert compare_observation(high, low, high) is Verdict.SUPPORTED
    assert compare_observation(Decimal("12.5001"), low, high) is Verdict.CONTRADICTED
    assert compare_observation(None, low, high) is Verdict.NOT_VERIFIABLE
    assert compare_observation(Decimal("NaN"), low, high) is Verdict.NOT_VERIFIABLE
    with pytest.raises(ValueError):
        compare_observation(low, high, low)


def test_future_trading_session_does_not_complete_the_window() -> None:
    friday, monday, tuesday = (date(2026, 3, n) for n in (6, 9, 10))
    calendar = TradingCalendar([tuesday, friday, monday], as_of=tuesday)
    assert forecast_window(calendar, friday, monday, 2) == ForecastWindow(None, Verdict.FORWARD_WINDOW_INCOMPLETE)
    assert forecast_window(calendar, friday, tuesday, 2) == ForecastWindow(tuesday)
    assert forecast_window(calendar, tuesday, monday, 1) == ForecastWindow(None, Verdict.NOT_VERIFIABLE)
    assert forecast_window(calendar, date(2026, 3, 7), monday, 1) == ForecastWindow(None, Verdict.NOT_VERIFIABLE)
    with pytest.raises(ValueError):
        forecast_window(calendar, friday, monday, 0)
