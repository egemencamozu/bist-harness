import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from bistharness.analytics.claims import (
    ForecastWindow,
    Verdict,
    compare_observation,
    forecast_window,
    percent_change,
    quoted_percent_bounds,
)
from bistharness.core.calendar import TradingCalendar
from bistharness.core.config import load_settings, load_universe
from bistharness.core.pit import PITRepository
from bistharness.tools import ToolContext, run_tool
from bistharness.tools.speech_verification import verify_claim
from tests.conftest import insert_prices


def test_percent_change() -> None:
    assert percent_change(Decimal("155"), Decimal("100")) == Decimal("55")
    assert percent_change(Decimal("90"), Decimal("100")) == Decimal("-10")
    assert percent_change(Decimal("1"), Decimal("0")) is None
    assert percent_change(Decimal("NaN"), Decimal("100")) is None


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


def test_percentage_bounds_use_the_quoted_precision() -> None:
    assert quoted_percent_bounds("Hasılat %55,") == (Decimal("54.5"), Decimal("55.5"))
    assert quoted_percent_bounds("Faiz yüzde 4,50") == (Decimal("4.495"), Decimal("4.505"))
    assert quoted_percent_bounds("−%5,5") == (Decimal("-5.55"), Decimal("-5.45"))
    assert quoted_percent_bounds("from 3.5 percent to 4 percent") is None


def test_speech_tool_keeps_quotes_out_of_evidence_and_ignores_later_releases(mem_conn: sqlite3.Connection) -> None:
    pub = "2026-10-05 09:00:00"
    quote = "Şu anda yıllık TÜFE yüzde 40."
    mem_conn.execute(
        "INSERT INTO speech_segments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("sample", 0, 60, pub, "", "A", "B", quote, '["inflation"]', None, 1.0, "fixture"),
    )
    mem_conn.execute(
        "INSERT INTO speech_claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "one",
            "sample",
            0,
            pub,
            "seg",
            "extract",
            "MACRO",
            "macro_value",
            quote,
            '[["pct",40.0]]',
            "cpi_yoy",
            "none",
            None,
            "neutral",
            "high",
            "",
            "fixture",
        ),
    )
    mem_conn.execute(
        "INSERT INTO macro_observations VALUES (?,?,?,?,?,?,?)",
        ("TUFE_YOY", "2026-08-01", 40.2, "2026-09-03 10:00:00", "fixture", None, "fixture"),
    )
    ctx = ToolContext(PITRepository(mem_conn), load_settings(), load_universe())
    inp = {"source_id_or_topic": "sample", "as_of_date": "2026-10-06"}
    before = run_tool("get_speech_features", inp, ctx)
    assert before.result["claims"][0]["verification"]["status"] == Verdict.SUPPORTED
    check = next(item for item in before.evidence_candidates if item.key.startswith("speech_check."))
    assert check.display["observed"] == "%40,2000" and quote not in check.claim_tr
    assert "%40,0000" not in check.display.values()
    mem_conn.execute(
        "INSERT INTO macro_observations VALUES (?,?,?,?,?,?,?)",
        ("TUFE_YOY", "2026-08-01", 999.0, "2026-10-05 09:00:01", "fixture", None, "fixture"),
    )
    after = run_tool("get_speech_features", inp, ctx)
    assert before.output_hash == after.output_hash
    early = run_tool("get_speech_features", {**inp, "as_of_date": "2026-10-04"}, ctx)
    assert early.result["claims"] == []


def test_price_forecast_uses_known_close_and_requires_explicit_sessions(mem_conn: sqlite3.Connection) -> None:
    friday, monday, tuesday = (date(2026, 3, n) for n in (6, 9, 10))
    insert_prices(mem_conn, "THYAO", [friday, monday, tuesday], [100.0, 105.0, 110.0])
    ctx = ToolContext(PITRepository(mem_conn), load_settings(), load_universe())
    claim = {
        "subject": "THYAO",
        "published_at": "2026-03-06 19:00:00",
        "claim_type": "price_move_forecast",
        "metric": None,
        "direction": "up",
        "horizon_days": 2,
        "quote": "2 işlem günü içinde yükselecek.",
    }
    assert verify_claim(ctx, claim, monday)["status"] == Verdict.FORWARD_WINDOW_INCOMPLETE
    assert verify_claim(ctx, claim, tuesday)["status"] == Verdict.SUPPORTED
    assert (
        verify_claim(ctx, {**claim, "quote": "2 gün içinde yükselecek."}, tuesday)["status"] == Verdict.NOT_VERIFIABLE
    )


def test_approved_subject_can_supply_a_segment_missing_its_ticker_tag(mem_conn: sqlite3.Connection) -> None:
    pub = "2026-03-05 19:31:24"
    quote = "Hasılat yıllık bazda yüzde 20 arttı."
    mem_conn.execute(
        "INSERT INTO speech_segments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("sample", 0, 60, pub, "", "A", "B", quote, "[]", None, 1.0, "fixture"),
    )
    mem_conn.execute(
        "INSERT INTO speech_claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "claim",
            "sample",
            0,
            pub,
            "seg",
            "extract",
            "ENKAI",
            "fundamental_value",
            quote,
            '[["pct",20.0]]',
            "revenue_growth",
            "up",
            None,
            "neutral",
            "high",
            "",
            "fixture",
        ),
    )
    ctx = ToolContext(PITRepository(mem_conn), load_settings(), load_universe())
    inp = {"source_id_or_topic": "ENKAI", "as_of_date": "2026-03-05"}
    result = run_tool("get_speech_features", inp, ctx).result
    assert len(result["segments"]) == 1 and result["claims"][0]["claim_id"] == "claim"
    assert run_tool("get_speech_features", {**inp, "as_of_date": "2026-03-04"}, ctx).result["claims"] == []
