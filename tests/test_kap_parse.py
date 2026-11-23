"""KAP XBRL report parsing on synthetic disclosures that mimic the structures found in the 2026-11-21 dump."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from bistharness.core.config import project_root
from bistharness.core.enums import WarningCode
from bistharness.data.ingest import kap

FMAP = kap.load_fundamentals_map(project_root() / "config" / "fundamentals.yaml")
PL = "Kar veya Zarar Tablosu"
BS = "Finansal Durum Tablosu (Bilanço)"
CF = "Nakit Akış Tablosu (Dolaylı Yöntem)"
BANK_BS = "Bilanço (Finansal Durum Tablosu) (TFRS 9'a Göre Karşılık Ayrılmış)"
BANK_PL = "Kar veya Zarar Tablosu (TFRS 9'a Göre Karşılık Ayrılmış)"


def _i(concept: str, value: float | None, end: str | None, start: str | None = None, **kw: Any) -> dict[str, Any]:
    return {
        "concept": concept,
        "label": kw.get("label", concept),
        "member": kw.get("member"),
        "period_label": kw.get("period_label"),
        "period_start": start,
        "period_end": end,
        "value": value,
    }


def _st(name: str, items: list[dict[str, Any]], currency: str = "1.000 TL", cons: str = "Konsolide") -> dict[str, Any]:
    return {"statement": name, "currency": currency, "consolidation": cons, "items": items}


def _rec(statements: list[dict[str, Any]], *, year: int = 2026, term: int = 2, idx: int = 1) -> dict[str, Any]:
    return {
        "disclosure_index": idx,
        "publish_date": "2026-08-04 18:24:32",
        "stock_code": "SYN",
        "title": "Finansal Rapor",
        "year": year,
        "term": term,
        "financial_statements": statements,
    }


def _rows(rep: kap.ParsedReport) -> pd.DataFrame:
    return pd.DataFrame(rep.rows, columns=kap.ROW_COLUMNS)


def _one(df: pd.DataFrame, **match: object) -> pd.Series:
    sel = df
    for k, v in match.items():
        sel = sel[sel[k] == v]
    assert len(sel) == 1, f"{match}: {len(sel)} rows"
    return sel.iloc[0]


def test_units_are_normalised_and_columns_are_assigned_by_date_not_label() -> None:
    rec = _rec(
        [
            _st(
                PL,
                [
                    _i("ifrs-full_Revenue", 100.0, "2026-06-30", "2026-01-01", period_label="Cari Dönem"),
                    _i("ifrs-full_Revenue", 60.0, "2026-06-30", "2026-04-01", period_label="Cari Dönem 3 Aylık"),
                    _i("ifrs-full_Revenue", 80.0, "2025-06-30", "2025-01-01", period_label="Cari Dönem"),  # wrong label
                ],
                currency="1.000 TL",
            ),
            _st(
                BS,
                [_i("ifrs-full_Assets", 5.0, "2026-06-30"), _i("ifrs-full_Assets", 4.0, "2025-12-31")],
                "1.000.000 TL",
            ),
        ]
    )
    df = _rows(kap.parse_report(rec, "SYN", FMAP))
    assert _one(df, metric="revenue", fiscal_period="2026Q2", duration="6M")["value"] == 100_000.0
    assert _one(df, metric="revenue", fiscal_period="2026Q2", duration="3M")["value"] == 60_000.0
    prior = _one(df, metric="revenue", fiscal_period="2025Q2")
    assert prior["role"] == "prior" and prior["value"] == 80_000.0 and prior["report_period"] == "2026Q2"
    assert _one(df, metric="total_assets", fiscal_period="2026Q2")["value"] == 5_000_000.0
    bal_prior = _one(df, metric="total_assets", fiscal_period="2025Q4")
    assert bal_prior["duration"] == "instant" and bal_prior["role"] == "prior"
    assert set(df["scope"]) == {"consolidated"} and set(df["disclosure_datetime"]) == {"2026-08-04 18:24:32"}


def test_equity_change_oci_statements_and_dimension_members_are_ignored() -> None:
    rec = _rec(
        [
            _st(
                PL,
                [
                    _i("ifrs-full_ProfitLoss", 10.0, "2026-06-30", "2026-01-01"),
                    _i("ifrs-full_Revenue", 7.0, "2026-06-30", "2026-01-01", member="Segment A"),
                ],
            ),
            _st("Diğer Kapsamlı Gelir Tablosu", [_i("ifrs-full_ProfitLoss", 999.0, "2026-06-30", "2026-01-01")]),
            _st("Özkaynaklar Değişim Tablosu", [_i("ifrs-full_Equity", 999.0, "2026-06-30")]),
        ]
    )
    df = _rows(kap.parse_report(rec, "SYN", FMAP))
    assert _one(df, metric="net_income")["value"] == 10_000.0
    assert "revenue" not in set(df["metric"]) and "total_equity" not in set(df["metric"])


def test_unknown_unit_is_reported_and_never_guessed() -> None:
    rep = kap.parse_report(
        _rec([_st(PL, [_i("ifrs-full_Revenue", 1.0, "2026-06-30", "2026-01-01")], "USD")]), "SYN", FMAP
    )
    assert rep.rows == []
    assert [i.code for i in rep.issues][:1] == [WarningCode.FUNDAMENTAL_UNIT_UNKNOWN]


def test_non_calendar_fiscal_year_is_labelled_by_the_company_calendar() -> None:
    """MAVI-like: fiscal year February-January, reported as year 2025, term 4."""
    rec = _rec(
        [
            _st(
                PL,
                [
                    _i("ifrs-full_Revenue", 120.0, "2026-01-31", "2025-02-01"),
                    _i("ifrs-full_Revenue", 90.0, "2025-01-31", "2024-02-01"),
                    _i("ifrs-full_Revenue", 40.0, "2026-01-31", "2025-11-01"),
                ],
            ),
            _st(BS, [_i("ifrs-full_Assets", 9.0, "2026-01-31"), _i("ifrs-full_Assets", 8.0, "2025-01-31")]),
        ],
        year=2025,
        term=4,
    )
    df = _rows(kap.parse_report(rec, "SYN", FMAP))
    assert _one(df, metric="revenue", duration="12M", role="current")["fiscal_period"] == "2025Q4"
    assert _one(df, metric="revenue", duration="12M", role="prior")["fiscal_period"] == "2024Q4"
    assert _one(df, metric="revenue", duration="3M")["fiscal_period"] == "2025Q4"
    assert _one(df, metric="total_assets", role="prior")["fiscal_period"] == "2024Q4"


def test_bank_balance_sheet_totals_are_rebuilt_by_position_and_verified() -> None:
    def six(concept: str, v: list[float]) -> list[dict[str, Any]]:
        return [
            _i(concept, v[0], "2026-06-30", period_label="Cari Dönem"),  # actually current TL column
            _i(concept, v[1], "2025-12-31", period_label="Önceki Dönem"),  # actually current FX column
            *[_i(concept, x, None) for x in v[2:]],
        ]

    rec = _rec(
        [
            _st(
                BANK_BS,
                [*six("ifrs-full_Assets", [60, 40, 100, 50, 30, 80]), *six("kap-fr_Loans", [6, 4, 15, 5, 3, 8])],
            ),
            _st(BANK_PL, [_i("ifrs-full_ProfitLoss", 3.0, "2026-06-30", "2026-01-01")]),
        ]
    )
    rep = kap.parse_report(rec, "SYN", FMAP)
    df = _rows(rep)
    assert rep.fmt == "bank"
    assert _one(df, metric="total_assets", fiscal_period="2026Q2")["value"] == 100_000.0
    assert _one(df, metric="total_assets", fiscal_period="2025Q4")["value"] == 80_000.0
    assert "loans" not in set(df["metric"])  # 6 + 4 != 15 (beyond 1-unit rounding) -> not trusted
    issue = next(i for i in rep.issues if i.code is WarningCode.FUNDAMENTAL_COLUMNS_UNVERIFIED)
    assert "kap-fr_Loans" in issue.detail


def test_sum_metric_and_candidate_fallback() -> None:
    rec = _rec(
        [
            _st(
                BS,
                [
                    _i("kap-fr_CurrentBorowings", 10.0, "2026-06-30"),
                    _i("ifrs-full_LongtermBorrowings", 5.0, "2026-06-30"),
                ],
            ),
            _st(
                CF,
                [
                    _i(
                        "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                        -3.0,
                        "2026-06-30",
                        "2026-01-01",
                    )
                ],
            ),
        ]
    )
    df = _rows(kap.parse_report(rec, "SYN", FMAP))
    debt = _one(df, metric="financial_debt")
    assert debt["value"] == 15_000.0
    assert debt["source_ref"] == "kap:1#kap-fr_CurrentBorowings+ifrs-full_LongtermBorrowings"
    capex = _one(df, metric="capex")
    assert capex["value"] == -3_000.0 and capex["source_ref"].endswith(
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
    )


def test_resolve_ticker_and_fiscal_label() -> None:
    universe = {"GARAN", "ISCTR", "TRALT", "AKBNK"}
    aliases = {"KOZAL": "TRALT"}
    assert kap.resolve_ticker("GARAN, TGB", universe, aliases) == "GARAN"
    assert kap.resolve_ticker("ISATR, ISBTR, ISCTR, ISKUR, TIB", universe, aliases) == "ISCTR"
    assert kap.resolve_ticker("KOZAL", universe, aliases) == "TRALT"
    assert kap.resolve_ticker("XYZ", universe, aliases) is None
    assert kap.resolve_ticker("GARAN, AKBNK", universe, aliases) is None  # ambiguous
    assert kap.fiscal_label(2026, 2, date(2026, 6, 30), date(2025, 12, 31)) == "2025Q4"
    assert kap.fiscal_label(2026, 2, date(2026, 6, 30), date(2025, 6, 30)) == "2025Q2"
    assert kap.fiscal_label(2026, 2, date(2026, 6, 30), date(2026, 5, 31)) is None
    assert kap.duration_label(date(2026, 4, 1), date(2026, 6, 30)) == "3M"
    assert kap.duration_label(None, date(2026, 6, 30)) == "instant"


def _r(ticker: str, idx: int, pub: str, fiscal: str, end: str, role: str, value: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "fiscal_period": fiscal,
        "period_start": None,
        "period_end": end,
        "duration": "6M",
        "report_period": fiscal,
        "role": role,
        "disclosure_datetime": pub,
        "disclosure_index": idx,
        "scope": "consolidated",
        "statement": "income",
        "metric": "revenue",
        "value": value,
        "source_ref": None,
    }


def test_tms29_is_detected_from_restated_comparatives() -> None:
    rows = pd.DataFrame(
        [
            # A: restates its comparatives by ~30 % -> inflation-adjusted
            _r("A", 1, "2025-08-01 18:00:00", "2025Q2", "2025-06-30", "current", 100.0),
            _r("A", 2, "2026-08-01 18:00:00", "2026Q2", "2026-06-30", "current", 150.0),
            _r("A", 2, "2026-08-01 18:00:00", "2025Q2", "2025-06-30", "prior", 130.0),
            _r("A", 3, "2026-11-01 18:00:00", "2026Q3", "2026-09-30", "current", 200.0),  # no comparative -> inherits
            # B: comparatives unchanged -> nominal (functional currency not TRY)
            _r("B", 4, "2025-08-01 18:00:00", "2025Q2", "2025-06-30", "current", 100.0),
            _r("B", 5, "2026-08-01 18:00:00", "2026Q2", "2026-06-30", "current", 120.0),
            _r("B", 5, "2026-08-01 18:00:00", "2025Q2", "2025-06-30", "prior", 100.0),
            # C: interim report before the first mandatory application (FY2023) -> nominal by definition
            _r("C", 6, "2023-08-01 18:00:00", "2023Q2", "2023-06-30", "current", 100.0),
        ]
    )
    out = kap.detect_tms29(rows, FMAP).set_index("disclosure_index")["tms29_adjusted"]
    assert out.notna().all()
    assert bool(out[2]) is True
    assert bool(out[3]) is True
    assert bool(out[5]) is False
    assert bool(out[6]) is False
    assert bool(out[4]) is False  # 2025Q2 report of B: no comparative of its own, inherits B's decision
    assert np.isclose(kap.detect_tms29(rows, FMAP).set_index("disclosure_index").loc[2, "tms29_ratio"], 1.3)


def test_iter_financial_reports_filters_and_slims(tmp_path: Path) -> None:
    lines = [
        {**_rec([]), "text": "x" * 100, "tables": [1], "stock_code": "GARAN, TGB"},
        {**_rec([]), "title": "Faaliyet Raporu (Konsolide)", "stock_code": "GARAN"},
        {**_rec([]), "stock_code": "OTHER"},
    ]
    plain = tmp_path / "a.jsonl"
    plain.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
    packed = tmp_path / "b.jsonl.gz"
    with gzip.open(packed, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(lines[0], ensure_ascii=False) + "\n")
    got = list(kap.iter_financial_reports([plain, packed], {"GARAN"}))
    assert len(got) == 2
    assert all("text" not in r and "tables" not in r for r in got)


@pytest.mark.parametrize(
    ("names", "fmt"),
    [
        ([BANK_BS, BANK_PL], "bank"),
        (["Bilanço", "Gelir Tablosu", "Nakit Akım Tablosu"], "insurance"),
        ([BS, PL, CF], "tfrs"),
    ],
)
def test_statement_format(names: list[str], fmt: str) -> None:
    assert kap.statement_format(names) == fmt
