"""Macro snapshot, staleness, FX relationship and inflation compounding (synthetic series)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from bistharness.analytics import macro_stats as ms
from bistharness.core.enums import WarningCode


def _rows() -> pd.DataFrame:
    rows = []
    for i, d in enumerate(pd.bdate_range("2025-01-01", "2026-09-10")):
        rows.append(("USDTRY", d.date().isoformat(), 35.0 * 1.001**i, f"{d.date()} 15:30:00"))
    for d, v in [("2024-12-27", 47.5), ("2025-06-20", 46.0), ("2026-01-23", 37.0)]:
        rows.append(("TCMB_POLICY_RATE", d, v, f"{d} 00:00:00"))
    for d, v in [("2024-12-19", 4.5), ("2025-12-11", 3.75)]:
        rows.append(("FED_TARGET_UPPER", d, v, f"{d} 00:00:00"))
        rows.append(("FED_TARGET_LOWER", d, v - 0.25, f"{d} 00:00:00"))
    for m in pd.period_range("2025-01", "2026-08", freq="M"):
        obs = m.to_timestamp().date().isoformat()
        rows.append(("TUFE_MOM", obs, 2.0, f"{(m + 1).to_timestamp().date().isoformat()[:8]}03 10:00:00"))
        rows.append(("TUFE_YOY", obs, 40.0 - 0.5 * (m - pd.Period("2025-01", "M")).n, f"{obs[:8]}28 10:00:00"))
    return pd.DataFrame(rows, columns=["series_code", "obs_date", "value", "release_datetime"])


def test_snapshot_latest_values_and_changes() -> None:
    snap = ms.macro_snapshot(_rows(), date(2026, 9, 10))
    assert snap.latest["TCMB_POLICY_RATE"].value == 37.0
    assert snap.changes["TCMB_POLICY_RATE"]["12m"] == pytest.approx(37.0 - 46.0)
    assert snap.latest["TUFE_YOY"].obs_date == date(2026, 8, 1)
    assert snap.changes["TUFE_YOY"]["3m"] == pytest.approx(-1.5)  # vs May 2026 observation
    assert snap.real_policy_rate == pytest.approx(37.0 - snap.latest["TUFE_YOY"].value)
    assert snap.fed_mid == pytest.approx(3.625)
    assert [w.detail.split(":")[0] for w in snap.warnings] == ["EURTRY"]  # not in the synthetic rows


def test_missing_and_stale_series_warn() -> None:
    rows = _rows()
    rows = rows[~((rows["series_code"] == "USDTRY") & (rows["obs_date"] > "2026-08-20"))]
    rows = rows[rows["series_code"] != "EURTRY"]
    snap = ms.macro_snapshot(rows, date(2026, 9, 10))
    details = [w.detail for w in snap.warnings]
    assert all(w.code == WarningCode.MISSING_MACRO for w in snap.warnings)
    assert any(d.startswith("EURTRY: no value") for d in details)
    assert any(d.startswith("USDTRY: latest observation") for d in details)


def test_change_points() -> None:
    cp = ms.change_points(_rows(), "TCMB_POLICY_RATE")
    assert cp["value"].tolist() == [46.0, 37.0] and cp["previous"].tolist() == [47.5, 46.0]


def test_fx_relationship_recovers_a_known_beta() -> None:
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2024-01-01", periods=500)
    fx_r = rng.normal(0.001, 0.01, 500)
    fx = pd.Series(30 * np.exp(np.cumsum(fx_r)), index=idx)
    stock = pd.Series(100 * np.exp(np.cumsum(0.8 * fx_r + rng.normal(0, 0.002, 500))), index=idx)
    rel = ms.fx_relationship(stock, fx, frequency="D")
    assert rel.beta.beta == pytest.approx(0.8, abs=0.05) and rel.correlation.pearson > 0.9
    weekly = ms.fx_relationship(stock, fx)
    assert weekly.frequency == "W-FRI" and weekly.correlation.n < rel.correlation.n
    assert weekly.stock_return_in_fx == pytest.approx((1 + weekly.stock_return) / (1 + weekly.fx_return) - 1)
    # the period return runs between the stated first/last common days, whatever the frequency
    assert weekly.start == rel.start == idx[0].date() and weekly.end == idx[-1].date()
    assert weekly.stock_return == pytest.approx(stock.iloc[-1] / stock.iloc[0] - 1) == rel.stock_return
    assert weekly.fx_return == pytest.approx(fx.iloc[-1] / fx.iloc[0] - 1)


def test_inflation_compounding_and_real_return() -> None:
    infl = ms.inflation_between(_rows(), date(2026, 1, 15), date(2026, 3, 31))
    assert infl.months_used == infl.months_expected == 3 and infl.complete
    assert infl.cumulative == pytest.approx(1.02**3 - 1)
    assert ms.real_return(0.10, infl) == pytest.approx(1.10 / 1.02**3 - 1)
    partial = ms.inflation_between(_rows(), date(2026, 7, 1), date(2026, 10, 31))  # Sep/Oct not released
    assert (partial.months_used, partial.months_expected, partial.complete) == (2, 4, False)
