"""Scenario 4 analytics on synthetic KAP-shaped rows: report selection, decumulation, TTM, ratios, valuation,
template rules, disclosure timing and post-disclosure windows."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from bistharness.analytics import fundamentals as fa
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import FundamentalTemplate, WarningCode

END = {
    "2024Q2": "2024-06-30",
    "2025Q2": "2025-06-30",
    "2025Q3": "2025-09-30",
    "2025Q4": "2025-12-31",
    "2024Q4": "2024-12-31",
    "2026Q1": "2026-03-31",
    "2026Q2": "2026-06-30",
    "2024Q3": "2024-09-30",
    "2025Q1": "2025-03-31",
}


def _rows(report: str, idx: int, when: str, cur: dict, prior: dict, scope: str = "consolidated") -> list[dict]:
    """cur/prior: {(fiscal_period, duration): {metric: value}}."""
    out = []
    for role, block in (("current", cur), ("prior", prior)):
        for (fp, dur), metrics in block.items():
            for m, v in metrics.items():
                out.append(
                    {
                        "ticker": "SYN",
                        "fiscal_period": fp,
                        "period_start": None,
                        "period_end": END[fp],
                        "duration": dur,
                        "report_period": report,
                        "role": role,
                        "disclosure_datetime": when,
                        "disclosure_index": idx,
                        "scope": scope,
                        "statement": "x",
                        "metric": m,
                        "value": v,
                        "unit": "TRY",
                        "tms29_adjusted": 1,
                        "source": "synthetic",
                        "source_ref": f"kap:{idx}",
                    }
                )
    return out


def FLOW(rev: float, gp: float, ni: float) -> dict[str, float]:
    return {
        "revenue": rev,
        "gross_profit": gp,
        "marketing_expense": -0.1 * gp,
        "admin_expense": -0.1 * gp,
        "depreciation_amortization": 0.05 * rev,
        "operating_profit": 0.6 * gp,
        "net_income_parent": ni,
        "net_income": ni,
        "operating_cash_flow": 1.5 * ni,
    }


BAL = {
    "total_assets": 1000.0,
    "equity_parent": 400.0,
    "total_equity": 420.0,
    "financial_debt": 300.0,
    "cash": 100.0,
    "current_assets": 500.0,
    "current_liabilities": 250.0,
    "inventories": 100.0,
    "issued_capital": 10.0,
}

ROWS = pd.DataFrame(
    _rows("2024Q4", 10, "2025-03-01 18:30:00", {("2024Q4", "12M"): FLOW(360, 90, 36), ("2024Q4", "instant"): BAL}, {})
    + _rows(
        "2025Q3",
        20,
        "2025-11-05 18:30:00",
        {("2025Q3", "9M"): FLOW(300, 75, 30), ("2025Q3", "3M"): FLOW(100, 25, 10), ("2025Q3", "instant"): BAL},
        {},
    )
    + _rows(
        "2025Q4",
        30,
        "2026-03-02 18:30:00",
        {("2025Q4", "12M"): FLOW(420, 105, 42), ("2025Q4", "instant"): BAL},
        {("2024Q4", "12M"): FLOW(380, 95, 38)},
    )
    + _rows("2026Q1", 40, "2026-05-05 18:30:00", {("2026Q1", "3M"): FLOW(110, 30, 12), ("2026Q1", "instant"): BAL}, {})
    + _rows(
        "2026Q2",
        50,
        "2026-08-04 18:24:32",
        {("2026Q2", "6M"): FLOW(240, 66, 26), ("2026Q2", "3M"): FLOW(130, 36, 14), ("2026Q2", "instant"): BAL},
        {("2025Q2", "6M"): FLOW(200, 50, -5), ("2025Q2", "3M"): FLOW(105, 26, 11), ("2025Q4", "instant"): BAL},
    )
    + _rows("2026Q2", 51, "2026-08-04 18:24:32", {("2026Q2", "6M"): FLOW(1, 1, 1)}, {}, scope="solo")
)


def test_latest_version_and_scope_preference() -> None:
    corrected = pd.concat(
        [ROWS, pd.DataFrame(_rows("2026Q1", 45, "2026-05-20 09:00:00", {("2026Q1", "3M"): FLOW(111, 30, 12)}, {}))]
    )
    reps = fa.build_reports(corrected, ticker="SYN")
    assert reps["2026Q1"].disclosure_index == 45 and reps["2026Q1"].n_versions == 2
    assert reps["2026Q1"].ytd["revenue"] == 111
    assert reps["2026Q2"].scope == "consolidated" and reps["2026Q2"].ytd["revenue"] == 240


def test_quarter_ttm_growth_and_ebitda() -> None:
    reps = fa.build_reports(ROWS, ticker="SYN")
    q4 = fa.report_metrics(reps["2025Q4"], reps, template=FundamentalTemplate.INDUSTRIAL, tms29_applies=True)
    rev = q4.levels["revenue"]
    assert rev["quarter"].value == pytest.approx(420 - 300) and rev["quarter"].approx
    assert rev["quarter"].sources == (30, 20)
    assert rev["ttm"].value == 420 and not rev["ttm"].approx
    assert rev["yoy_ytd"].value == pytest.approx(420 / 380 - 1) and rev["yoy_ytd"].basis == "same_report_yoy"
    assert any(w.code == WarningCode.TMS29_DECUMULATION_APPROX for w in q4.warnings)

    q2 = fa.report_metrics(reps["2026Q2"], reps, template=FundamentalTemplate.INDUSTRIAL, tms29_applies=True)
    assert q2.levels["revenue"]["ttm"].value == pytest.approx(240 + 420 - 200)
    assert q2.levels["revenue"]["yoy_quarter"].value == pytest.approx(130 / 105 - 1)
    assert not q2.levels["revenue"]["yoy_quarter"].approx  # both 3M columns of the same report
    assert q2.levels["revenue"]["qoq"].value == pytest.approx(130 / 110 - 1)
    ni = q2.levels["net_income_parent"]["yoy_ytd"]
    assert ni.value is None and ni.reason == "BASE_NOT_POSITIVE"  # prior-year YTD was a loss
    assert q2.levels["ebitda"]["ytd"].value == pytest.approx(66 - 0.2 * 66 + 0.05 * 240)


def test_ratios() -> None:
    reps = fa.build_reports(ROWS, ticker="SYN")
    m = fa.report_metrics(reps["2026Q2"], reps, template=FundamentalTemplate.INDUSTRIAL, tms29_applies=True).ratios
    assert m["net_debt"].value == 200 and m["debt_to_equity"].value == pytest.approx(300 / 420)
    assert m["current_ratio"].value == 2.0 and m["quick_ratio"].value == pytest.approx(400 / 250)
    assert m["roe"].value == pytest.approx((26 + 42 - (-5)) / 400) and m["roe"].approx
    assert m["gross_margin"].value == pytest.approx(66 / 240) and m["gross_margin"].unit == "ratio"
    assert m["net_debt_to_ebitda"].unit == "x"


def test_template_rules_bank_and_brokerage() -> None:
    reps = fa.build_reports(ROWS, ticker="SYN")
    broker = fa.report_metrics(reps["2026Q2"], reps, template=FundamentalTemplate.BROKERAGE, tms29_applies=True)
    for name in ("ebitda_margin", "net_debt_to_ebitda", "current_ratio", "quick_ratio"):
        assert broker.ratios[name].value is None
        assert broker.ratios[name].reason == WarningCode.NOT_APPLICABLE_FOR_TEMPLATE
    assert broker.levels["ebitda"]["ytd"].reason == WarningCode.NOT_APPLICABLE_FOR_TEMPLATE
    bank_rows = pd.DataFrame(
        _rows(
            "2026Q2",
            60,
            "2026-07-28 18:00:00",
            {
                ("2026Q2", "6M"): {
                    "net_interest_income": 50.0,
                    "net_income_parent": 20.0,
                    "net_income": 20.0,
                    "personnel_expense": -10.0,
                    "other_operating_expense": -8.0,
                    "gross_operating_profit": 60.0,
                },
                ("2026Q2", "instant"): {
                    "loans": 600.0,
                    "deposits": 750.0,
                    "total_equity": 100.0,
                    "total_assets": 1000.0,
                },
            },
            {},
        )
    )
    breps = fa.build_reports(bank_rows, ticker="SYN")
    bank = fa.report_metrics(breps["2026Q2"], breps, template=FundamentalTemplate.BANK, tms29_applies=False)
    assert bank.ratios["loans_to_deposits"].value == pytest.approx(0.8)
    assert bank.ratios["cost_to_income"].value == pytest.approx(18 / 60)
    assert bank.ratios["current_ratio"].reason == WarningCode.NOT_APPLICABLE_FOR_TEMPLATE
    val = fa.valuation(bank, breps, day=date(2026, 9, 10), raw_close=50.0, actions=pd.DataFrame())
    assert val.metrics["ev_to_ebitda"].reason == WarningCode.NOT_APPLICABLE_FOR_TEMPLATE


def test_valuation_adjusts_shares_for_bonus_issues_after_period_end() -> None:
    reps = fa.build_reports(ROWS, ticker="SYN")
    rm = fa.report_metrics(reps["2026Q2"], reps, template=FundamentalTemplate.INDUSTRIAL, tms29_applies=True)
    actions = pd.DataFrame(
        {
            "ex_date": ["2026-05-01", "2026-07-15", "2026-09-20"],
            "ratio": [2.0, 3.0, 5.0],
            "kind": ["split_or_bonus", "split_or_bonus", "split_or_bonus"],
        }
    )
    v = fa.valuation(rm, reps, day=date(2026, 9, 10), raw_close=4.0, actions=actions)
    assert v.shares == 30.0  # 10 x 3 (bonus after 2026-06-30, before the valuation day); May one already in capital
    assert v.market_cap == 120.0
    assert v.metrics["pb"].value == pytest.approx(120 / 400)
    assert v.metrics["pe"].value == pytest.approx(120 / (26 + 42 + 5))


def test_comparison_flags_tms29_and_nominal() -> None:
    reps = fa.build_reports(ROWS, ticker="SYN")
    old = fa.report_metrics(reps["2024Q4"], reps, template=FundamentalTemplate.INDUSTRIAL, tms29_applies=True)
    new = fa.report_metrics(reps["2026Q2"], reps, template=FundamentalTemplate.INDUSTRIAL, tms29_applies=True)
    ch = fa.compare_reports(old, new, tms29_consistent_from=date(2025, 1, 1))
    assert ch.tms29_warning and [w.code for w in ch.warnings] == [WarningCode.TMS29_WARNING]
    gm = next(c for c in ch.changes if c.name == "gross_margin")
    assert gm.kind == "difference" and gm.change == pytest.approx(66 / 240 - 90 / 360)
    recent = fa.report_metrics(reps["2026Q1"], reps, template=FundamentalTemplate.INDUSTRIAL, tms29_applies=False)
    nominal = fa.compare_reports(
        recent,
        fa.report_metrics(reps["2026Q2"], reps, template=FundamentalTemplate.INDUSTRIAL, tms29_applies=False),
        tms29_consistent_from=date(2025, 1, 1),
    )
    assert not nominal.tms29_warning and [w.code for w in nominal.warnings] == [WarningCode.NOMINAL_VALUES]


DAYS = pd.bdate_range("2026-07-27", "2026-09-10")
CAL = TradingCalendar((d.date() for d in DAYS), as_of=date(2026, 9, 10))


@pytest.mark.parametrize(
    ("when", "base", "timing"),
    [
        ("2026-08-04 18:24:32", date(2026, 8, 4), "after_close"),  # TUPRS golden case
        ("2026-08-05 08:00:00", date(2026, 8, 4), "before_or_during_session"),  # pre-session
        ("2026-08-05 14:00:00", date(2026, 8, 4), "before_or_during_session"),
        ("2026-08-08 11:00:00", date(2026, 8, 7), "non_trading_day"),  # Saturday
        ("2026-08-05", date(2026, 8, 5), "time_unknown"),
    ],
)
def test_reaction_base_day(when: str, base: date, timing: str) -> None:
    bd = fa.reaction_base_day(when, CAL)
    assert (bd.base_day, bd.timing) == (base, timing)
    assert (bd.warning is not None) == (timing == "time_unknown")


def test_post_disclosure_windows_follow_the_completeness_rule() -> None:
    close = pd.Series(100 * 1.001 ** np.arange(len(DAYS)), index=DAYS)
    bench = pd.Series(100.0, index=DAYS)
    reps = fa.build_reports(ROWS, ticker="SYN")
    late = fa.build_reports(
        pd.DataFrame(_rows("2026Q2", 70, "2026-08-17 18:30:00", {("2026Q2", "6M"): FLOW(1, 1, 1)}, {})), ticker="SYN"
    )["2026Q2"]
    study = fa.post_disclosure_reactions([reps["2026Q2"], late], close, CAL, benchmark=bench)
    tuprs_like = study.table[study.table["disclosure_index"] == 50]
    assert sorted(tuprs_like["horizon"]) == [1, 3, 5, 10, 20]  # 27 trading days after 2026-08-04
    bimas_like = [(e.horizon, e.trading_days_available) for e in study.excluded]
    assert bimas_like == [(20, 18)]  # BIMAS golden case: 18 trading days after 2026-08-17
    h5 = tuprs_like[tuprs_like["horizon"] == 5].iloc[0]
    assert h5["abn_benchmark"] == pytest.approx(1.001**5 - 1)
    labels = {"2026Q2": "improved"}
    grouped = fa.group_reactions(study.table, labels, horizon=5)
    assert grouped["improved"].n == 2  # type: ignore[union-attr]
