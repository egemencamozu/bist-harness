from __future__ import annotations

from datetime import date

import pytest

from bistharness.core.calendar import TradingCalendar
from tests.conftest import business_days


@pytest.fixture
def cal() -> TradingCalendar:
    days = business_days("2026-08-03", 30)  # Mon 2026-08-03 .. Fri 2026-09-11
    return TradingCalendar(days, as_of=date(2026, 9, 10))


def test_days_after_as_of_are_discarded(cal: TradingCalendar) -> None:
    assert cal.last == date(2026, 9, 10)
    assert not cal.is_trading_day(date(2026, 9, 11))


def test_event_on_as_of_has_no_complete_window(cal: TradingCalendar) -> None:
    w = cal.window(date(2026, 9, 10), 1)
    assert not w.complete
    assert w.trading_days_available == 0


def test_partial_window_reports_available_days(cal: TradingCalendar) -> None:
    ev = date(2026, 9, 7)  # Mon; Tue/Wed/Thu (8, 9, 10) are known -> 3 days
    assert cal.window(ev, 1).complete
    assert cal.window(ev, 3).complete
    assert cal.window(ev, 3).end_date == date(2026, 9, 10)
    w5 = cal.window(ev, 5)
    assert not w5.complete
    assert w5.trading_days_available == 3


def test_window_skips_weekends(cal: TradingCalendar) -> None:
    assert cal.nth_after(date(2026, 9, 4), 1) == date(2026, 9, 7)  # Fri -> Mon


def test_split_complete_never_drops_silently(cal: TradingCalendar) -> None:
    events = [date(2026, 8, 3), date(2026, 9, 1), date(2026, 9, 9)]
    complete, excluded = cal.split_complete(events, [1, 5, 20], event_type="bb_lower_touch", ticker="ASELS")
    assert complete[1] == events  # all three have a t+1 known
    assert complete[5] == [date(2026, 8, 3), date(2026, 9, 1)]
    assert complete[20] == [date(2026, 8, 3)]
    # every (event, horizon) pair is either complete or explicitly excluded
    assert sum(len(v) for v in complete.values()) + len(excluded) == len(events) * 3
    ex = {(e.event_date, e.horizon) for e in excluded}
    assert (date(2026, 9, 9), 5) in ex
    assert all(e.reason == "FORWARD_WINDOW_INCOMPLETE" and e.ticker == "ASELS" for e in excluded)


def test_event_after_as_of_is_incomplete(cal: TradingCalendar) -> None:
    assert not cal.window(date(2026, 9, 11), 1).complete
