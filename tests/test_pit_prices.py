"""Poisoned-future tests for prices: rows and corporate actions after as_of must not change any output."""

from __future__ import annotations

import sqlite3
from datetime import date

import numpy as np
import pandas as pd
import pytest

from bistharness.core.enums import WarningCode
from bistharness.core.errors import AsOfRequiredError, DataNotFoundError, LookAheadError
from bistharness.core.pit import PITRepository
from tests.conftest import business_days, insert_prices

AS_OF = date(2026, 9, 10)


def _base(conn: sqlite3.Connection) -> list[date]:
    days = business_days("2026-08-03", 30)
    past = [d for d in days if d <= AS_OF]
    insert_prices(conn, "AAA", past, [100.0 + i for i in range(len(past))])
    return days


def test_as_of_is_mandatory(mem_conn: sqlite3.Connection) -> None:
    _base(mem_conn)
    repo = PITRepository(mem_conn)
    with pytest.raises(TypeError):
        repo.prices("AAA", "2026-08-01", "2026-09-10")  # type: ignore[call-arg]
    with pytest.raises(AsOfRequiredError):
        repo.prices("AAA", "2026-08-01", "2026-09-10", as_of=None)
    with pytest.raises(AsOfRequiredError):
        repo.trading_calendar(as_of="")


def test_poisoned_future_rows_are_invisible(mem_conn: sqlite3.Connection) -> None:
    days = _base(mem_conn)
    repo = PITRepository(mem_conn)
    clean = repo.prices("AAA", "2026-08-01", "2026-12-31", as_of=AS_OF).data

    future = [d for d in days if d > AS_OF] + [date(2027, 1, 4)]
    insert_prices(mem_conn, "AAA", future, [9_999_999.0] * len(future))
    poisoned = repo.prices("AAA", "2026-08-01", "2026-12-31", as_of=AS_OF).data

    pd.testing.assert_frame_equal(clean, poisoned)
    assert poisoned["date"].max() == pd.Timestamp(AS_OF)
    assert len(repo.trading_calendar(as_of=AS_OF)) == len([d for d in days if d <= AS_OF])


def test_future_corporate_action_does_not_rescale_history(mem_conn: sqlite3.Connection) -> None:
    """A 2:1 split after as_of changes the stored cum_factor of ALL past rows; anchoring must cancel it."""
    days = business_days("2026-08-03", 30)
    past = [d for d in days if d <= AS_OF]
    closes = [100.0 + i for i in range(len(past))]
    insert_prices(mem_conn, "AAA", past, closes, factors=[1.0] * len(past))
    repo = PITRepository(mem_conn)
    before = repo.prices("AAA", as_of=AS_OF).data

    # re-ingest the same history as it would look after a future split: every past factor halves
    insert_prices(mem_conn, "AAA", past, closes, factors=[0.5] * len(past))
    future = [d for d in days if d > AS_OF]
    insert_prices(mem_conn, "AAA", future, [55.0] * len(future), factors=[1.0] * len(future))
    after = repo.prices("AAA", as_of=AS_OF).data

    pd.testing.assert_frame_equal(before, after)
    # levels at as_of equal the prices actually printed that day
    assert after["close"].iloc[-1] == pytest.approx(closes[-1])


def test_past_corporate_action_is_adjusted_and_anchored(mem_conn: sqlite3.Connection) -> None:
    days = business_days("2026-08-03", 20)
    raw = [100.0] * 10 + [50.0] * 10  # 2:1 bonus on day 10
    factors = [0.5] * 10 + [1.0] * 10
    insert_prices(mem_conn, "BBB", days, raw, factors=factors)
    df = PITRepository(mem_conn).prices("BBB", as_of=days[-1]).data
    assert np.allclose(df["close"], 50.0)  # no artificial -50% jump
    assert np.allclose(df["raw_close"].iloc[:10], 100.0)
    # turnover-preserving volume: pre-bonus volume doubles
    assert df["volume"].iloc[0] == pytest.approx(2 * df["raw_volume"].iloc[0])

    # as_of before the bonus: levels are the pre-bonus printed prices
    early = PITRepository(mem_conn).prices("BBB", as_of=days[5]).data
    assert np.allclose(early["close"], 100.0)


def test_end_after_as_of_is_clamped_with_warning(mem_conn: sqlite3.Connection) -> None:
    _base(mem_conn)
    res = PITRepository(mem_conn).prices("AAA", "2026-08-01", "2026-12-31", as_of=AS_OF)
    assert res.end == AS_OF
    assert any(w.code is WarningCode.END_CLAMPED_TO_AS_OF for w in res.warnings)


def test_as_of_beyond_data_is_reported(mem_conn: sqlite3.Connection) -> None:
    _base(mem_conn)
    res = PITRepository(mem_conn).prices("AAA", as_of=date(2026, 12, 31))
    assert any(w.code is WarningCode.AS_OF_BEYOND_DATA for w in res.warnings)


def test_unknown_ticker_raises(mem_conn: sqlite3.Connection) -> None:
    _base(mem_conn)
    with pytest.raises(DataNotFoundError):
        PITRepository(mem_conn).prices(["AAA", "ZZZ"], as_of=AS_OF)


def test_post_check_catches_leaks() -> None:
    df = pd.DataFrame({"date": ["2026-09-09", "2026-09-11"]})
    with pytest.raises(LookAheadError):
        PITRepository._post_check(df, "date", "2026-09-10", "unit-test")
