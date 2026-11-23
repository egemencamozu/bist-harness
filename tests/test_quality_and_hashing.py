from __future__ import annotations

from datetime import date

import pandas as pd

from bistharness.core.enums import Severity, ToolStatus, WarningCode
from bistharness.core.hashing import canonical_json, sha256_hex
from bistharness.core.schemas import ToolEnvelope
from bistharness.data.quality import check_jumps, check_ohlc, check_stale, check_zero_volume


def _frame() -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=6)
    return pd.DataFrame(
        {
            "open": [10, 10, 10, 10, 10, 10.0],
            "high": [11, 11, 9.5, 11, 11, 11.0],  # day 2: high below open/close
            "low": [9, 9, 9, 9, 9, -1.0],  # day 5: non-positive
            "close": [10, 10, 10, 10, 10, 10.0],
            "volume": [1, 0, 1, 1, 1, 1.0],
        },
        index=idx,
    )


def test_ohlc_checks() -> None:
    f = _frame()
    flags = check_ohlc("X", f)
    codes = {(x.code, x.date) for x in flags}
    assert (WarningCode.OHLC_INCONSISTENT, f.index[2].date()) in codes
    assert (WarningCode.NON_POSITIVE_PRICE, f.index[5].date()) in codes
    assert all(x.severity is Severity.HARD for x in flags if x.code is WarningCode.NON_POSITIVE_PRICE)


def test_jump_thresholds() -> None:
    s = pd.Series([100, 105, 118, 59, 60.0], index=pd.bdate_range("2024-01-01", periods=5))
    flags = check_jumps("X", s, suspicious=0.105, broken=0.30)
    by_code = {x.code: x for x in flags}
    assert WarningCode.SUSPICIOUS_JUMP in by_code  # +12.4 %
    assert by_code[WarningCode.BROKEN_PRICE_SERIES].severity is Severity.HARD  # -50 %


def test_stale_and_zero_volume() -> None:
    f = _frame()
    stale = check_stale("X", f["close"], run_days=5)
    assert len(stale) == 1 and stale[0].date == f.index[4].date()
    zero = check_zero_volume("X", f["volume"])
    assert [z.date for z in zero] == [f.index[1].date()]


def test_canonical_json_is_order_independent() -> None:
    a = {"b": 1, "a": [1, 2], "d": date(2026, 9, 10)}
    b = {"d": date(2026, 9, 10), "a": [1, 2], "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert sha256_hex(a) == sha256_hex(b)


def test_envelope_hashes_are_deterministic() -> None:
    def make() -> ToolEnvelope:
        return ToolEnvelope(
            tool="get_stock_history",
            tool_version="1.0.0",
            as_of_date=date(2026, 9, 10),
            inputs={"ticker": "THYAO", "start": "2024-01-01"},
            status=ToolStatus.OK,
            result={"rows": 3},
        ).finalize()

    e1, e2 = make(), make()
    assert e1.call_id == e2.call_id and e1.output_hash == e2.output_hash
    e3 = e1.model_copy(update={"inputs": {"ticker": "ASELS", "start": "2024-01-01"}}).finalize()
    assert e3.call_id != e1.call_id
