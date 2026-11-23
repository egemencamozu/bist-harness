"""Macro source parsers and release-time rules (synthetic payloads in the formats observed on 2026-11-21)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from bistharness.data.ingest import macro

SYNTHETIC_FX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Tarih_Date Tarih="10.09.2024" Date="09/10/2024" Bulten_No="2024/170">
  <Currency CrossOrder="0" Kod="USD" CurrencyCode="USD"><Unit>1</Unit><ForexBuying>34.0000</ForexBuying>
    <ForexSelling>34.1000</ForexSelling></Currency>
  <Currency CrossOrder="9" Kod="EUR" CurrencyCode="EUR"><Unit>1</Unit><ForexBuying>37.5000</ForexBuying>
    <ForexSelling>37.6000</ForexSelling></Currency>
  <Currency CrossOrder="12" Kod="JPY" CurrencyCode="JPY"><Unit>100</Unit><ForexBuying>23.0000</ForexBuying>
    <ForexSelling>23.2000</ForexSelling></Currency>
</Tarih_Date>"""

SYNTHETIC_REPO_HTML = """<table><tr><th>Tarih</th><th>Borç Alma</th><th>Borç Verme</th></tr>
<tr><td>12.12.2025</td><td>-</td><td>38.00</td></tr>
<tr><td> 23.01.2026 </td><td>-</td><td>37.00</td></tr>
<tr><td>not a date</td><td>-</td><td>1</td></tr></table>"""

SYNTHETIC_CPI_HTML = """<table><tr><th>Ay-Yıl</th><th>TÜFE (Yıllık % Değişim)</th><th>TÜFE (Aylık % Değişim)</th></tr>
<tr><td>08-2026</td><td>31.51</td><td>1.84</td></tr><tr><td>07-2026</td><td>31.75</td><td>1.78</td></tr></table>"""

SYNTHETIC_FRED_CSV = "observation_date,DFEDTARU\n2025-09-16,4.50\n2025-09-17,4.50\n2025-09-18,4.25\n2025-09-19,.\n"


def test_tcmb_fx_xml_takes_forex_buying_per_unit() -> None:
    d, rates = macro.parse_tcmb_fx_xml(SYNTHETIC_FX_XML)
    assert d == date(2024, 9, 10)
    assert rates == {"USD": 34.0, "EUR": 37.5}  # JPY is not a tracked series


def test_policy_table_uses_effective_date_as_conservative_release() -> None:
    obs = macro.policy_observations(SYNTHETIC_REPO_HTML)
    assert [(o.obs_date, o.value, o.release_datetime) for o in obs] == [
        ("2025-12-12", 38.0, "2025-12-12 00:00:00"),
        ("2026-01-23", 37.0, "2026-01-23 00:00:00"),
    ]


def test_cpi_release_is_third_or_next_trading_day_at_ten() -> None:
    trading = [date(2026, 8, 3), date(2026, 8, 4), date(2026, 9, 3), date(2026, 9, 4)]
    obs = {(o.series_code, o.obs_date): o for o in macro.cpi_observations(SYNTHETIC_CPI_HTML, trading)}
    assert obs[("TUFE_YOY", "2026-08-01")].release_datetime == "2026-09-03 10:00:00"
    assert obs[("TUFE_MOM", "2026-07-01")].value == 1.78
    # 3 Aug 2024 was a Saturday -> next trading day (Mon 5 Aug)
    assert macro.cpi_release(date(2024, 7, 1), [date(2024, 8, 2), date(2024, 8, 5)]) == "2024-08-05 10:00:00"
    # beyond the known calendar: weekday rule (3 Jan 2027 is a Sunday)
    assert macro.cpi_release(date(2026, 12, 1), [date(2026, 11, 19)]) == "2027-01-04 10:00:00"


def test_fred_keeps_change_points_only() -> None:
    obs = macro.fred_observations("DFEDTARU", SYNTHETIC_FRED_CSV)
    assert [(o.obs_date, o.value) for o in obs] == [("2025-09-16", 4.5), ("2025-09-18", 4.25)]
    assert all(o.series_code == "FED_TARGET_UPPER" and o.release_datetime.endswith("00:00:00") for o in obs)


def test_change_points_and_weekdays() -> None:
    s = pd.Series([1.0, 1.0, 2.0, 2.0, 1.0], index=pd.date_range("2026-01-01", periods=5))
    assert list(macro.change_points(s)) == [1.0, 2.0, 1.0]
    days = list(macro.weekdays(date(2026, 11, 13), date(2026, 11, 17)))
    assert days == [date(2026, 11, 13), date(2026, 11, 16)]
