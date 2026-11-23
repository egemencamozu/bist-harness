"""Parse KAP 'Finansal Rapor' disclosures (XBRL financial statements) into canonical long rows.

Source: the user's KAP dump (`data/external/kapdata/*.jsonl`, one disclosure per line). Disclosures titled
"Finansal Rapor" carry `financial_statements = [{statement, currency, consolidation, items: [{concept, label, member,
period_label, period_start, period_end, value}]}]`. Metric mapping: `config/fundamentals.yaml`.

Rules (CLAUDE.md §2, §3, §11), each found in the 2026-11-21 profile of the dump:

* Knowledge time = `publish_date` (KAP publication, seconds, Europe/Istanbul). A correction is a separate disclosure
  (`is_changed = DUZENLENEN`, linked by `related_disclosure_oid`) and becomes a later version. The original's own
  `is_changed = DUZELTILEN` marker was written after the fact (look-ahead) and is never used.
* Values are normalised to TRY with the statement's `currency` scale ("TL", "1.000 TL", "1.000.000 TL"); the scale
  changes between reports of the same company (AKBNK: thousands until 2026Q1, millions from 2026Q2).
* Current vs prior column is decided by dates, never by `period_label` (wrong on bank balance sheets, see below).
* Fiscal period labels follow the company's fiscal calendar (MAVI's fiscal year ends in January).
* BDDK bank balance sheets have 6 columns per line (current TL/FX/Total, prior TL/FX/Total) but the dump dates only
  the first two (labelled "Cari Dönem" / "Önceki Dönem" although they are current TL and current FX). Totals are
  rebuilt by position and kept only when TL + FX = Total holds for both periods.
* Statements of changes in equity, off-balance-sheet (Nazım) and OCI-only statements are skipped, and so are items
  with an XBRL `member` (dimension breakdowns).
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from bistharness.core.enums import Severity, WarningCode
from bistharness.core.errors import ConfigError

TITLE = "Finansal Rapor"
UNIT_SCALE: dict[str, float] = {"TL": 1.0, "1.000 TL": 1_000.0, "1.000.000 TL": 1_000_000.0}
SCOPES = {"Konsolide": "consolidated", "Konsolide Olmayan": "solo"}
STATEMENT_KINDS = ("balance", "income", "cashflow")
DROP_KEYS = frozenset({"text", "tables", "fields", "attachments"})
ROW_COLUMNS = [
    "ticker",
    "fiscal_period",
    "period_start",
    "period_end",
    "duration",
    "report_period",
    "role",
    "disclosure_datetime",
    "disclosure_index",
    "scope",
    "statement",
    "metric",
    "value",
    "source_ref",
]


# --------------------------------------------------------------------------- mapping config
@dataclass(frozen=True)
class MetricSpec:
    metric: str
    statement: str  # balance | income | cashflow
    concepts: tuple[str, ...]
    is_sum: bool = False


@dataclass(frozen=True)
class FundamentalsMap:
    formats: dict[str, tuple[MetricSpec, ...]]
    tms29_metrics: tuple[str, ...]
    restated_ratio: float
    unchanged_tolerance: float
    first_application_period_end: date

    def concepts(self, fmt: str) -> frozenset[str]:
        return frozenset(c for spec in self.formats[fmt] for c in spec.concepts)


def fundamentals_map_from_dict(raw: dict[str, Any]) -> FundamentalsMap:
    formats: dict[str, tuple[MetricSpec, ...]] = {}
    for fmt, statements in raw["formats"].items():
        specs: list[MetricSpec] = []
        for kind, metrics in statements.items():
            if kind not in STATEMENT_KINDS:
                raise ConfigError(f"fundamentals.yaml: unknown statement kind {kind!r} in format {fmt}")
            for metric, spec in metrics.items():
                if isinstance(spec, dict) and "sum" in spec:
                    specs.append(MetricSpec(metric, kind, tuple(spec["sum"]), is_sum=True))
                elif isinstance(spec, list) and spec:
                    specs.append(MetricSpec(metric, kind, tuple(spec)))
                else:
                    raise ConfigError(f"fundamentals.yaml: bad spec for {fmt}.{kind}.{metric}: {spec!r}")
        names = [s.metric for s in specs]
        if len(names) != len(set(names)):
            raise ConfigError(f"fundamentals.yaml: duplicate metric names in format {fmt}")
        formats[fmt] = tuple(specs)
    det = raw["tms29_detection"]
    return FundamentalsMap(
        formats=formats,
        tms29_metrics=tuple(det["metrics"]),
        restated_ratio=float(det["restated_ratio"]),
        unchanged_tolerance=float(det["unchanged_tolerance"]),
        first_application_period_end=date.fromisoformat(str(det["first_application_period_end"])),
    )


def load_fundamentals_map(path: Path) -> FundamentalsMap:
    with path.open("r", encoding="utf-8") as fh:
        return fundamentals_map_from_dict(yaml.safe_load(fh))


# --------------------------------------------------------------------------- reading the dump
def iter_financial_reports(files: Iterable[Path], codes: set[str]) -> Iterator[dict[str, Any]]:
    """Yield 'Finansal Rapor' disclosures that mention any of `codes`, without the heavy text/table fields."""
    for path in files:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if f'"{TITLE}"' not in line:  # cheap pre-filter; the JSON check below is authoritative
                    continue
                rec = json.loads(line)
                if rec.get("title") != TITLE:
                    continue
                if not set(split_codes(rec.get("stock_code"))) & codes:
                    continue
                yield {k: v for k, v in rec.items() if k not in DROP_KEYS}


def split_codes(stock_code: object) -> list[str]:
    return [c.strip() for c in str(stock_code or "").split(",") if c.strip()]


def resolve_ticker(stock_code: object, tickers: set[str], aliases: dict[str, str]) -> str | None:
    """KAP lists all codes of an issuer ("GARAN, TGB"). Return the single universe ticker among them, else None."""
    hits = {aliases.get(c, c) for c in split_codes(stock_code)} & tickers
    return hits.pop() if len(hits) == 1 else None


# --------------------------------------------------------------------------- parsing one report
@dataclass(frozen=True)
class Issue:
    ticker: str
    disclosure_index: int
    disclosure_datetime: str
    code: WarningCode
    severity: Severity
    detail: str

    def as_row(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "disclosure_index": self.disclosure_index,
            "disclosure_datetime": self.disclosure_datetime,
            "code": self.code.value,
            "severity": self.severity.value,
            "detail": self.detail,
        }


@dataclass
class ParsedReport:
    ticker: str
    disclosure_index: int
    disclosure_datetime: str
    report_period: str
    period_end: date | None
    scope: str
    fmt: str
    rows: list[dict[str, object]] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def statement_format(names: Sequence[str]) -> str:
    if any("TFRS 9" in n for n in names):
        return "bank"
    if "Gelir Tablosu" in names and any(n.startswith("Nakit Akım") for n in names):
        return "insurance"
    return "tfrs"


def statement_kind(name: str, all_names: Sequence[str]) -> str | None:
    if "Değişim" in name or "Nazım" in name or name.startswith("Diğer Kapsamlı Gelir"):
        return None
    if "Nakit Ak" in name:
        return "cashflow"
    if "Bilanço" in name or "Finansal Durum" in name:
        return "balance"
    if name.startswith("Kar veya Zarar ve Diğer Kapsamlı") and any(
        n.startswith("Kar veya Zarar Tablosu") for n in all_names
    ):
        return None  # OCI-only statement: the separate P&L statement is used instead
    if "Kar veya Zarar" in name or name == "Gelir Tablosu":
        return "income"
    return None


def _d(s: object) -> date | None:
    return date.fromisoformat(str(s)[:10]) if s else None


def duration_label(start: date | None, end: date) -> str:
    if start is None:
        return "instant"
    return f"{(end.year - start.year) * 12 + end.month - start.month + 1}M"


def fiscal_label(year: int, term: int, report_end: date, period_end: date) -> str | None:
    """Fiscal quarter of `period_end`, counted back from the report's own (year, term) in steps of 3 months."""
    months_back = (report_end.year - period_end.year) * 12 + (report_end.month - period_end.month)
    if months_back < 0 or months_back % 3:
        return None
    idx = year * 4 + (term - 1) - months_back // 3
    return f"{idx // 4}Q{idx % 4 + 1}"


_Key = tuple[date | None, date]  # (period_start, period_end)


def _bank_balance_values(
    items: list[dict[str, Any]], scale: float, wanted: frozenset[str]
) -> tuple[dict[str, dict[_Key, float]], list[str]]:
    """Rebuild the Total columns of a BDDK balance sheet by position; returns values and unverifiable concepts."""
    by_concept: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_concept.setdefault(it["concept"], []).append(it)
    out: dict[str, dict[_Key, float]] = {}
    bad: list[str] = []
    for concept, its in by_concept.items():
        if len(its) != 6 or _d(its[0]["period_end"]) is None or _d(its[1]["period_end"]) is None:
            if concept in wanted:
                bad.append(f"{concept} ({len(its)} columns)")
            continue
        v = [float(i["value"]) if i["value"] is not None else np.nan for i in its]
        cur_end, prior_end = _d(its[0]["period_end"]), _d(its[1]["period_end"])
        assert cur_end is not None and prior_end is not None

        def ok(tl: float, fx: float, tot: float) -> bool:
            return bool(np.isfinite([tl, fx, tot]).all()) and abs(tl + fx - tot) <= 1.0 + 1e-9 * abs(tot)

        if not (ok(v[0], v[1], v[2]) and ok(v[3], v[4], v[5])):
            if concept in wanted:
                bad.append(f"{concept} (TL+FX != Total)")
            continue
        out[concept] = {(None, cur_end): v[2] * scale, (None, prior_end): v[5] * scale}
    return out, bad


def parse_report(rec: dict[str, Any], ticker: str, fmap: FundamentalsMap) -> ParsedReport:
    idx = int(rec["disclosure_index"])
    published = str(rec["publish_date"])
    statements: list[dict[str, Any]] = rec.get("financial_statements") or []
    names = [str(s.get("statement") or "") for s in statements]
    fmt = statement_format(names)
    scopes = {SCOPES.get(str(s.get("consolidation")), "unknown") for s in statements}
    scope = scopes.pop() if len(scopes) == 1 else "mixed"
    year, term = int(rec.get("year") or 0), int(rec.get("term") or 0)
    rep = ParsedReport(ticker, idx, published, f"{year}Q{term}", None, scope, fmt)

    def issue(code: WarningCode, sev: Severity, detail: str) -> None:
        rep.issues.append(Issue(ticker, idx, published, code, sev, detail))

    if scope not in {"consolidated", "solo"} or not 1 <= term <= 4 or year < 2000:
        issue(
            WarningCode.FUNDAMENTAL_REPORT_UNUSABLE,
            Severity.SOFT,
            f"unusable report header: scope={scope} year={year} term={term}",
        )
        return rep

    wanted = fmap.concepts(fmt)
    values: dict[str, dict[str, dict[_Key, float]]] = {k: {} for k in STATEMENT_KINDS}
    conflicts: list[str] = []
    for st, name in zip(statements, names, strict=True):
        kind = statement_kind(name, names)
        if kind is None:
            continue
        scale = UNIT_SCALE.get(str(st.get("currency")))
        if scale is None:
            issue(WarningCode.FUNDAMENTAL_UNIT_UNKNOWN, Severity.SOFT, f"{name}: unknown unit {st.get('currency')!r}")
            continue
        items = [i for i in st.get("items") or [] if not i.get("member") and i.get("concept")]
        if fmt == "bank" and kind == "balance" and any(i.get("period_end") is None for i in items):
            got, bad = _bank_balance_values(items, scale, wanted)
            values[kind].update(got)
            if bad:
                issue(WarningCode.FUNDAMENTAL_COLUMNS_UNVERIFIED, Severity.SOFT, f"{name}: " + "; ".join(sorted(bad)))
            continue
        bucket = values[kind]
        for i in items:
            end = _d(i.get("period_end"))
            if end is None or i.get("value") is None:
                continue
            key = (_d(i.get("period_start")), end)
            val = float(i["value"]) * scale
            prev = bucket.setdefault(i["concept"], {}).setdefault(key, val)
            if prev != val and i["concept"] in wanted:
                conflicts.append(f"{i['concept']}@{key[1]}")
    if conflicts:
        issue(
            WarningCode.FUNDAMENTAL_VALUE_CONFLICT,
            Severity.INFO,
            f"{len(conflicts)} repeated line(s) with different values, first kept: {', '.join(sorted(set(conflicts))[:5])}",
        )

    ends = [k[1] for kind in values.values() for per in kind.values() for k in per]
    if not ends:
        issue(WarningCode.FUNDAMENTAL_REPORT_UNUSABLE, Severity.SOFT, "no dated values in the report")
        return rep
    report_end = max(ends)
    rep.period_end = report_end

    unmapped: set[date] = set()
    for spec in fmap.formats[fmt]:
        bucket = values[spec.statement]
        keys = sorted({k for c in spec.concepts for k in bucket.get(c, {})}, key=lambda k: (k[1], k[0] or k[1]))
        for key in keys:
            present = [(c, bucket[c][key]) for c in spec.concepts if key in bucket.get(c, {})]
            if spec.is_sum:
                value = float(sum(v for _, v in present))
                ref = "+".join(c for c, _ in present)
            else:
                ref, value = present[0]
            start, end = key
            fiscal = fiscal_label(year, term, report_end, end)
            if fiscal is None:
                unmapped.add(end)
                continue
            rep.rows.append(
                {
                    "ticker": ticker,
                    "fiscal_period": fiscal,
                    "period_start": start.isoformat() if start else None,
                    "period_end": end.isoformat(),
                    "duration": duration_label(start, end),
                    "report_period": rep.report_period,
                    "role": "current" if end == report_end else "prior",
                    "disclosure_datetime": published,
                    "disclosure_index": idx,
                    "scope": scope,
                    "statement": spec.statement,
                    "metric": spec.metric,
                    "value": value,
                    "source_ref": f"kap:{idx}#{ref}",
                }
            )
    if unmapped:
        issue(
            WarningCode.FUNDAMENTAL_PERIOD_UNMAPPED,
            Severity.INFO,
            f"values at {sorted(d.isoformat() for d in unmapped)} are not a whole number of quarters before "
            f"{report_end.isoformat()}; skipped",
        )
    return rep


# --------------------------------------------------------------------------- TMS 29 detection
def detect_tms29(rows: pd.DataFrame, fmap: FundamentalsMap) -> pd.DataFrame:
    """Per report: was it inflation-restated (TMS 29)? Evidence = its prior-period column vs the first-reported value.

    Returns columns ticker, scope, disclosure_index, tms29_adjusted (bool | None), tms29_basis, tms29_ratio.
    Reports for periods before the first mandatory application (FY2023) are nominal by definition. Inconclusive
    reports inherit the nearest conclusive decision of the same ticker and scope.
    """
    keys = ["ticker", "scope", "metric", "fiscal_period", "duration"]
    reports = (
        rows[["ticker", "scope", "disclosure_index", "disclosure_datetime", "report_period"]]
        .drop_duplicates("disclosure_index")
        .merge(
            rows[rows["role"] == "current"].groupby("disclosure_index")["period_end"].max().rename("report_end"),
            on="disclosure_index",
            how="left",
        )
    )
    originals = (
        rows[rows["role"] == "current"]
        .sort_values(["disclosure_datetime", "disclosure_index"], kind="stable")
        .drop_duplicates(keys)[[*keys, "value"]]
        .rename(columns={"value": "original"})
    )
    priors = rows[(rows["role"] == "prior") & rows["metric"].isin(fmap.tms29_metrics)].merge(originals, on=keys)
    priors = priors[(priors["original"].abs() > 0) & (np.sign(priors["value"]) == np.sign(priors["original"]))]
    priors = priors.assign(ratio=priors["value"] / priors["original"])
    order = {m: i for i, m in enumerate(fmap.tms29_metrics)}
    priors = priors.assign(rank=priors["metric"].map(order))
    best = priors[priors["rank"] == priors.groupby("disclosure_index")["rank"].transform("min")]
    evidence = best.groupby("disclosure_index").agg(tms29_basis=("metric", "first"), tms29_ratio=("ratio", "median"))
    out = reports.merge(evidence, on="disclosure_index", how="left")

    first_app = fmap.first_application_period_end.isoformat()

    def decide(r: pd.Series) -> object:
        if pd.notna(r["report_end"]) and str(r["report_end"]) < first_app:
            return False
        ratio = r["tms29_ratio"]
        if pd.isna(ratio):
            return None
        if ratio > fmap.restated_ratio:
            return True
        if abs(ratio - 1.0) <= fmap.unchanged_tolerance:
            return False
        return None

    out["tms29_adjusted"] = out.apply(decide, axis=1).astype(object)
    out = out.sort_values(["ticker", "scope", "report_end", "disclosure_datetime"], kind="stable")
    post = out["report_end"].astype(str) >= first_app  # nominal reports never vote for later ones
    filled = out[post].groupby(["ticker", "scope"])["tms29_adjusted"].transform(lambda s: s.ffill().bfill())
    out.loc[post, "tms29_adjusted"] = out.loc[post, "tms29_adjusted"].where(
        out.loc[post, "tms29_adjusted"].notna(), filled
    )
    return out[["ticker", "scope", "disclosure_index", "tms29_adjusted", "tms29_basis", "tms29_ratio"]].reset_index(
        drop=True
    )


__all__ = [
    "ROW_COLUMNS",
    "UNIT_SCALE",
    "FundamentalsMap",
    "Issue",
    "MetricSpec",
    "ParsedReport",
    "detect_tms29",
    "duration_label",
    "fiscal_label",
    "fundamentals_map_from_dict",
    "iter_financial_reports",
    "load_fundamentals_map",
    "parse_report",
    "resolve_ticker",
    "split_codes",
    "statement_format",
    "statement_kind",
]
