"""Scenario 4 — point-in-time fundamental metrics, quarterly changes and post-disclosure reactions (pure).

Input: rows of PITRepository.fundamentals(..., role=None, latest_only=False) — every version of every report
published up to as_of. Nothing here can see a later report.

Reports. For each fiscal period the latest version (corrections included) of the preferred scope
(consolidated, else solo) is used. A KAP report carries, for its fiscal quarter q:
- YTD flows (3M/6M/9M/12M for q = 1..4) and, for q = 2/3, the quarter-only 3M column; prior-year comparatives of both;
- balance-sheet instants at period end and the previous fiscal year end (comparative).
Both columns of one report are in the same purchasing power, so SAME-REPORT comparisons are the primary ones under
TMS 29 (CLAUDE.md §3). Values combining different reports carry TMS29_DECUMULATION_APPROX for TMS 29 reporters:
- Q4 quarter value = 12M(Q4 report) - 9M(Q3 report);
- TTM = YTD(q) + 12M(previous year's Q4 report) - prior-year YTD(q) (q = 4: the 12M itself);
- QoQ growth = quarter(q) / quarter(q-1) - 1 (quarter(q-1) from the previous report).

Definitions (KAP signs: expenses are negative, D&A is the positive cash-flow add-back):
EBITDA = gross_profit + marketing + admin + R&D expenses + depreciation_amortization (missing expense line = 0;
gross profit or D&A missing -> None). Net debt = financial_debt - cash. ROE = TTM net income (parent) / period-end
equity (parent; banks/insurers: total equity). ROA = TTM net income / total assets. Margins use YTD values.
Valuation at a day d: market cap = printed close(d) x shares, shares = issued capital (nominal 1 TL per share) of
the report x every split/bonus ratio with ex-date in (period_end, d]. P/E = cap / TTM net income (parent),
P/B = cap / equity, EV/EBITDA = (cap + net debt) / TTM EBITDA. Ratios that do not fit the template are not computed
(reason NOT_APPLICABLE_FOR_TEMPLATE, CLAUDE.md §3). Growth on a non-positive base is undefined (BASE_NOT_POSITIVE).

Reaction base day (CLAUDE.md §2 KAP timing): disclosure on a trading day after the close time -> that day's close;
before or during the session -> previous trading day's close; on a non-trading day -> the last trading day before;
no time of day -> treated as after close + DISCLOSURE_TIME_UNKNOWN.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time

import numpy as np
import pandas as pd

from bistharness.analytics import stats
from bistharness.analytics.forward_returns import CalendarIndex, event_outcomes
from bistharness.core.calendar import TradingCalendar
from bistharness.core.enums import (
    FINANCIAL_TEMPLATES,
    INDUSTRIAL_ONLY_METRICS,
    Direction,
    FundamentalTemplate,
    Severity,
    WarningCode,
)
from bistharness.core.schemas import ExcludedEvent, WarningItem

YTD_DURATION = {1: "3M", 2: "6M", 3: "9M", 4: "12M"}
SCOPE_PREFERENCE = ("consolidated", "solo")

# Level metrics (TRY) analysed per template; the first one is the "top line".
LEVEL_METRICS: dict[str, tuple[str, ...]] = {
    "tfrs": ("revenue", "gross_profit", "ebitda", "operating_profit", "net_income_parent", "operating_cash_flow"),
    "bank": ("net_interest_income", "net_fee_commission_income", "operating_profit", "net_income_parent"),
    "insurance": ("gross_written_premiums", "technical_balance", "net_income_parent"),
}
RATIO_METRICS: dict[str, tuple[str, ...]] = {
    "tfrs": (
        "gross_margin",
        "ebitda_margin",
        "operating_margin",
        "net_margin",
        "roe",
        "roa",
        "net_debt",
        "net_debt_to_ebitda",
        "debt_to_equity",
        "current_ratio",
        "quick_ratio",
        "cash_conversion",
    ),
    "bank": ("roe", "roa", "loans_to_deposits", "equity_to_assets", "cost_to_income"),
    "insurance": ("roe", "roa"),
}
VALUATION_METRICS: dict[str, tuple[str, ...]] = {
    "tfrs": ("pe", "pb", "ev_to_ebitda"),
    "bank": ("pe", "pb"),
    "insurance": ("pe", "pb"),
}
# Units for display: TRY amounts, plain ratios (0.123 = 12.3%) and multiples (x).
MULTIPLES = frozenset(
    {
        "net_debt_to_ebitda",
        "debt_to_equity",
        "current_ratio",
        "quick_ratio",
        "cash_conversion",
        "loans_to_deposits",
        "pe",
        "pb",
        "ev_to_ebitda",
    }
)


def statement_format(template: FundamentalTemplate) -> str:
    if template is FundamentalTemplate.BANK:
        return "bank"
    if template is FundamentalTemplate.INSURANCE:
        return "insurance"
    return "tfrs"


def quarter_of(fiscal_period: str) -> int:
    if len(fiscal_period) != 6 or fiscal_period[4] != "Q" or fiscal_period[5] not in "1234":
        raise ValueError(f"bad fiscal period {fiscal_period!r}")
    return int(fiscal_period[5])


def shift_period(fiscal_period: str, quarters: int) -> str:
    y, q = int(fiscal_period[:4]), quarter_of(fiscal_period)
    idx = y * 4 + (q - 1) + quarters
    return f"{idx // 4}Q{idx % 4 + 1}"


@dataclass(frozen=True)
class Report:
    ticker: str
    fiscal_period: str
    period_end: date
    disclosure_index: int
    disclosure_datetime: str
    scope: str
    tms29_adjusted: bool | None
    n_versions: int  # disclosures of this fiscal period+scope known at as_of (2+ = corrected)
    ytd: dict[str, float]
    quarter: dict[str, float]  # 3M column (Q1: = ytd)
    prior_ytd: dict[str, float]
    prior_quarter: dict[str, float]
    balance: dict[str, float]
    prior_balance: dict[str, float]  # previous fiscal year end, same report

    @property
    def q(self) -> int:
        return quarter_of(self.fiscal_period)


def _vals(df: pd.DataFrame) -> dict[str, float]:
    return {str(m): float(v) for m, v in zip(df["metric"], df["value"], strict=True) if pd.notna(v)}


def build_reports(rows: pd.DataFrame, *, ticker: str) -> dict[str, Report]:
    """fiscal_period -> Report (latest version known at as_of, preferred scope)."""
    if rows.empty:
        return {}
    out: dict[str, Report] = {}
    for period, grp in rows.groupby("report_period", sort=True):
        scope = next((s for s in SCOPE_PREFERENCE if (grp["scope"] == s).any()), str(grp["scope"].iloc[0]))
        g = grp[grp["scope"] == scope]
        versions = g.drop_duplicates("disclosure_index").sort_values(["disclosure_datetime", "disclosure_index"])
        latest = versions.iloc[-1]
        r = g[g["disclosure_index"] == latest["disclosure_index"]]
        q = quarter_of(str(period))
        cur, pri = r[r["role"] == "current"], r[r["role"] == "prior"]
        cur_p = cur[cur["fiscal_period"] == period]
        flows_dur = YTD_DURATION[q]
        tms = r["tms29_adjusted"].dropna()
        out[str(period)] = Report(
            ticker=ticker,
            fiscal_period=str(period),
            period_end=date.fromisoformat(str(cur_p["period_end"].max() if len(cur_p) else r["period_end"].max())),
            disclosure_index=int(latest["disclosure_index"]),
            disclosure_datetime=str(latest["disclosure_datetime"]),
            scope=scope,
            tms29_adjusted=bool(tms.max()) if len(tms) else None,
            n_versions=len(versions),
            ytd=_vals(cur_p[cur_p["duration"] == flows_dur]),
            quarter=_vals(cur_p[cur_p["duration"] == "3M"]),
            prior_ytd=_vals(pri[pri["duration"] == flows_dur]),
            prior_quarter=_vals(pri[pri["duration"] == "3M"]),
            balance=_vals(cur_p[cur_p["duration"] == "instant"]),
            prior_balance=_vals(pri[pri["duration"] == "instant"]),
        )
    return out


# ----------------------------------------------------------------------------------------------- metric values
@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float | None
    unit: str  # "TRY" | "ratio" | "x"
    basis: str  # ytd | quarter | ttm | instant | same_report_yoy | cross_report | valuation
    reason: str | None = None  # why value is None
    approx: bool = False  # combines different reports of a TMS 29 reporter
    sources: tuple[int, ...] = ()  # KAP disclosure indices used


def _unit(name: str) -> str:
    if name in MULTIPLES:
        return "x"
    if name.endswith(("_margin", "roe", "roa", "equity_to_assets", "cost_to_income")) or name in ("roe", "roa"):
        return "ratio"
    return "TRY"


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0 or not math.isfinite(a) or not math.isfinite(b):
        return None
    return a / b


def ebitda(flows: Mapping[str, float]) -> float | None:
    if "gross_profit" not in flows or "depreciation_amortization" not in flows:
        return None
    return (
        flows["gross_profit"]
        + sum(flows.get(k, 0.0) for k in ("marketing_expense", "admin_expense", "rnd_expense"))
        + flows["depreciation_amortization"]
    )


def _with_derived(flows: Mapping[str, float], fmt: str) -> dict[str, float]:
    out = dict(flows)
    if fmt == "tfrs":
        e = ebitda(flows)
        if e is not None:
            out["ebitda"] = e
    return out


@dataclass
class ReportMetrics:
    report: Report
    template: FundamentalTemplate
    tms29_applies: bool
    levels: dict[str, dict[str, MetricValue]]  # metric -> {"ytd","quarter","ttm","yoy_ytd","yoy_quarter","qoq"}
    ratios: dict[str, MetricValue]
    warnings: list[WarningItem] = field(default_factory=list)


def _quarter_value(
    rep: Report, metric: str, reports: Mapping[str, Report], fmt: str
) -> tuple[float | None, bool, tuple[int, ...]]:
    """Quarter-only value: the report's own 3M column, else Q4 decumulation 12M - 9M(previous report)."""
    cur_q = _with_derived(rep.quarter, fmt)
    if rep.q == 1:
        v = _with_derived(rep.ytd, fmt).get(metric)
        return v, False, (rep.disclosure_index,)
    if metric in cur_q:
        return cur_q[metric], False, (rep.disclosure_index,)
    prev = reports.get(shift_period(rep.fiscal_period, -1))
    if prev is None:
        return None, False, ()
    a, b = _with_derived(rep.ytd, fmt).get(metric), _with_derived(prev.ytd, fmt).get(metric)
    if a is None or b is None:
        return None, False, ()
    return a - b, True, (rep.disclosure_index, prev.disclosure_index)


def _prior_quarter_value(
    rep: Report, metric: str, reports: Mapping[str, Report], fmt: str
) -> tuple[float | None, bool]:
    if rep.q == 1:
        return _with_derived(rep.prior_ytd, fmt).get(metric), False
    pq = _with_derived(rep.prior_quarter, fmt)
    if metric in pq:
        return pq[metric], False
    # Q4: prior 12M (this report) - prior-year Q3 9M (an older report)
    old_q3 = reports.get(shift_period(rep.fiscal_period, -5))
    a = _with_derived(rep.prior_ytd, fmt).get(metric)
    b = _with_derived(old_q3.ytd, fmt).get(metric) if old_q3 is not None else None
    return (a - b, True) if a is not None and b is not None else (None, False)


def ttm(
    rep: Report, metric: str, reports: Mapping[str, Report], fmt: str
) -> tuple[float | None, bool, tuple[int, ...]]:
    ytd = _with_derived(rep.ytd, fmt).get(metric)
    if rep.q == 4:
        return ytd, False, (rep.disclosure_index,)
    fy = reports.get(f"{int(rep.fiscal_period[:4]) - 1}Q4")
    prior = _with_derived(rep.prior_ytd, fmt).get(metric)
    fy_v = _with_derived(fy.ytd, fmt).get(metric) if fy is not None else None
    if ytd is None or prior is None or fy_v is None or fy is None:
        return None, False, ()
    return ytd + fy_v - prior, True, (rep.disclosure_index, fy.disclosure_index)


def growth(a: float | None, b: float | None) -> tuple[float | None, str | None]:
    if a is None or b is None:
        return None, "MISSING_INPUT"
    if b <= 0:
        return None, "BASE_NOT_POSITIVE"
    return a / b - 1, None


def report_metrics(
    rep: Report,
    reports: Mapping[str, Report],
    *,
    template: FundamentalTemplate,
    tms29_applies: bool,
) -> ReportMetrics:
    fmt = statement_format(template)
    approx_flag = tms29_applies  # cross-report arithmetic is only an approximation for TMS 29 reporters
    src = (rep.disclosure_index,)
    ytd = _with_derived(rep.ytd, fmt)
    prior_ytd = _with_derived(rep.prior_ytd, fmt)
    levels: dict[str, dict[str, MetricValue]] = {}
    used_approx = False
    for m in LEVEL_METRICS[fmt]:
        qv, q_cross, q_src = _quarter_value(rep, m, reports, fmt)
        pqv, pq_cross = _prior_quarter_value(rep, m, reports, fmt)
        tv, t_cross, t_src = ttm(rep, m, reports, fmt)
        prev = reports.get(shift_period(rep.fiscal_period, -1))
        prev_q = _quarter_value(prev, m, reports, fmt) if prev is not None else (None, False, ())
        g_yoy, r_yoy = growth(ytd.get(m), prior_ytd.get(m))
        g_qyoy, r_qyoy = growth(qv, pqv)
        g_qoq, r_qoq = growth(qv, prev_q[0])
        qoq_src = tuple(sorted(set(q_src) | set(prev_q[2])))
        entry = {
            "ytd": MetricValue(m, ytd.get(m), "TRY", "ytd", None if m in ytd else "MISSING_INPUT", sources=src),
            "quarter": MetricValue(
                m,
                qv,
                "TRY",
                "quarter",
                None if qv is not None else "MISSING_INPUT",
                approx=q_cross and approx_flag,
                sources=q_src,
            ),
            "ttm": MetricValue(
                m,
                tv,
                "TRY",
                "ttm",
                None if tv is not None else "MISSING_INPUT",
                approx=t_cross and approx_flag,
                sources=t_src,
            ),
            "yoy_ytd": MetricValue(m, g_yoy, "ratio", "same_report_yoy", r_yoy, sources=src),
            "yoy_quarter": MetricValue(
                m,
                g_qyoy,
                "ratio",
                "same_report_yoy" if not (q_cross or pq_cross) else "cross_report",
                r_qyoy,
                approx=(q_cross or pq_cross) and approx_flag,
                sources=src,
            ),
            "qoq": MetricValue(
                m, g_qoq, "ratio", "cross_report", r_qoq, approx=approx_flag and g_qoq is not None, sources=qoq_src
            ),
        }
        if template in FINANCIAL_TEMPLATES and m in INDUSTRIAL_ONLY_METRICS:
            entry = {k: _not_applicable(m, v.basis) for k, v in entry.items()}
        used_approx |= any(v.approx for v in entry.values())
        levels[m] = entry

    ratios = _ratios(rep, reports, fmt, template, approx_flag)
    used_approx |= any(v.approx for v in ratios.values())
    warnings: list[WarningItem] = []
    if used_approx:
        warnings.append(
            WarningItem(
                code=WarningCode.TMS29_DECUMULATION_APPROX,
                severity=Severity.SOFT,
                detail=f"{rep.ticker} {rep.fiscal_period}: values combining different reports (quarter/TTM/QoQ) mix "
                "purchasing powers under TMS 29; same-report YoY is the primary comparison",
                ticker=rep.ticker,
            )
        )
    if rep.n_versions > 1:
        warnings.append(
            WarningItem(
                code=WarningCode.FUNDAMENTAL_VALUE_CONFLICT,
                severity=Severity.INFO,
                detail=f"{rep.ticker} {rep.fiscal_period}: {rep.n_versions} versions known; latest "
                f"(KAP {rep.disclosure_index}) used",
                ticker=rep.ticker,
            )
        )
    return ReportMetrics(rep, template, tms29_applies, levels, ratios, warnings)


def _ratios(
    rep: Report, reports: Mapping[str, Report], fmt: str, template: FundamentalTemplate, approx_flag: bool
) -> dict[str, MetricValue]:
    b = rep.balance
    y = _with_derived(rep.ytd, fmt)
    src = (rep.disclosure_index,)
    out: dict[str, MetricValue] = {}

    def put(name: str, value: float | None, basis: str, approx: bool = False, sources: tuple[int, ...] = src) -> None:
        out[name] = MetricValue(
            name,
            value,
            _unit(name),
            basis,
            None if value is not None else "MISSING_INPUT",
            approx=approx and value is not None,
            sources=sources,
        )

    equity = b.get("equity_parent", b.get("total_equity")) if fmt == "tfrs" else b.get("total_equity")
    ni_ttm, ni_cross, ni_src = ttm(rep, "net_income_parent", reports, fmt)
    nt_ttm, nt_cross, nt_src = ttm(rep, "net_income", reports, fmt)
    put("roe", _div(ni_ttm, equity), "ttm", ni_cross and approx_flag, ni_src)
    put("roa", _div(nt_ttm, b.get("total_assets")), "ttm", nt_cross and approx_flag, nt_src)
    if fmt == "tfrs":
        rev = y.get("revenue")
        put("gross_margin", _div(y.get("gross_profit"), rev), "ytd")
        put("ebitda_margin", _div(y.get("ebitda"), rev), "ytd")
        put("operating_margin", _div(y.get("operating_profit"), rev), "ytd")
        put("net_margin", _div(y.get("net_income_parent"), rev), "ytd")
        nd = b["financial_debt"] - b["cash"] if "financial_debt" in b and "cash" in b else None
        put("net_debt", nd, "instant")
        e_ttm, e_cross, e_src = ttm(rep, "ebitda", reports, fmt)
        put(
            "net_debt_to_ebitda",
            _div(nd, e_ttm) if e_ttm is not None and e_ttm > 0 else None,
            "ttm",
            e_cross and approx_flag,
            e_src,
        )
        put("debt_to_equity", _div(b.get("financial_debt"), b.get("total_equity")), "instant")
        put("current_ratio", _div(b.get("current_assets"), b.get("current_liabilities")), "instant")
        quick = b["current_assets"] - b.get("inventories", 0.0) if "current_assets" in b else None
        put("quick_ratio", _div(quick, b.get("current_liabilities")), "instant")
        ni_ytd = y.get("net_income")
        put("cash_conversion", _div(y.get("operating_cash_flow"), ni_ytd) if ni_ytd and ni_ytd > 0 else None, "ytd")
    elif fmt == "bank":
        put("loans_to_deposits", _div(b.get("loans"), b.get("deposits")), "instant")
        put("equity_to_assets", _div(b.get("total_equity"), b.get("total_assets")), "instant")
        opex = None
        if "personnel_expense" in y and "other_operating_expense" in y:
            opex = -(y["personnel_expense"] + y["other_operating_expense"])
        put("cost_to_income", _div(opex, y.get("gross_operating_profit")), "ytd")
    if template in FINANCIAL_TEMPLATES:
        for name in sorted(INDUSTRIAL_ONLY_METRICS - {"ebitda", "ev_to_ebitda"}):
            basis = out[name].basis if name in out else "instant"
            out[name] = _not_applicable(name, basis)
    return out


def _not_applicable(name: str, basis: str) -> MetricValue:
    return MetricValue(name, None, _unit(name), basis, WarningCode.NOT_APPLICABLE_FOR_TEMPLATE.value)


# ----------------------------------------------------------------------------------------------- valuation
@dataclass(frozen=True)
class Valuation:
    day: date
    fiscal_period: str
    price: float
    shares: float | None
    market_cap: float | None
    metrics: dict[str, MetricValue]
    share_count_approx: bool


def shares_at(rep: Report, actions: pd.DataFrame, day: date) -> tuple[float | None, bool]:
    """Issued capital (1 TL nominal per share) x split/bonus ratios with ex-date in (period_end, day]."""
    cap = rep.balance.get("issued_capital")
    if cap is None or cap <= 0:
        return None, False
    if actions is None or actions.empty:
        return cap, False
    ex = pd.to_datetime(actions["ex_date"]).dt.date
    window = (ex > rep.period_end) & (ex <= day)
    splits = actions[window & (actions["kind"] == "split_or_bonus")]
    approx = bool((window & (actions["kind"] == "rights_or_other")).any())
    return cap * float(np.prod(splits["ratio"].to_numpy(dtype=float))), approx


def valuation(
    rm: ReportMetrics,
    reports: Mapping[str, Report],
    *,
    day: date,
    raw_close: float,
    actions: pd.DataFrame,
) -> Valuation:
    rep = rm.report
    fmt = statement_format(rm.template)
    shares, approx = shares_at(rep, actions, day)
    cap = raw_close * shares if shares is not None else None
    b = rep.balance
    equity = b.get("equity_parent", b.get("total_equity")) if fmt == "tfrs" else b.get("total_equity")
    ni_ttm, ni_cross, ni_src = ttm(rep, "net_income_parent", reports, fmt)
    metrics: dict[str, MetricValue] = {}

    def put(
        name: str, value: float | None, cross: bool = False, sources: tuple[int, ...] = (rep.disclosure_index,)
    ) -> None:
        metrics[name] = MetricValue(
            name,
            value,
            "x",
            "valuation",
            None if value is not None else "MISSING_INPUT",
            approx=(cross and rm.tms29_applies) and value is not None,
            sources=sources,
        )

    put("pe", _div(cap, ni_ttm) if ni_ttm is not None and ni_ttm > 0 else None, ni_cross, ni_src)
    put("pb", _div(cap, equity) if equity is not None and equity > 0 else None)
    if fmt == "tfrs":
        e_ttm, e_cross, e_src = ttm(rep, "ebitda", reports, fmt)
        nd = rm.ratios.get("net_debt")
        ev = cap + nd.value if cap is not None and nd is not None and nd.value is not None else None
        put("ev_to_ebitda", _div(ev, e_ttm) if e_ttm is not None and e_ttm > 0 else None, e_cross, e_src)
    if rm.template in FINANCIAL_TEMPLATES:
        metrics["ev_to_ebitda"] = _not_applicable("ev_to_ebitda", "valuation")
    return Valuation(day, rep.fiscal_period, raw_close, shares, cap, metrics, approx)


# ----------------------------------------------------------------------------------------------- changes
@dataclass(frozen=True)
class MetricChange:
    name: str
    basis: str
    old: float | None
    new: float | None
    change: float | None  # ratios: new - old (fraction points); TRY levels: new / old - 1
    kind: str  # "difference" | "relative"
    reason: str | None


@dataclass
class FundamentalChange:
    ticker: str
    old_period: str
    new_period: str
    changes: list[MetricChange]
    tms29_warning: bool
    warnings: list[WarningItem]


def compare_reports(old: ReportMetrics, new: ReportMetrics, *, tms29_consistent_from: date) -> FundamentalChange:
    """Change of every ratio (difference) and every level (relative, YTD / quarter / TTM) between two reports."""
    changes: list[MetricChange] = []
    for name, nv in new.ratios.items():
        ov = old.ratios.get(name)
        o, n = (ov.value if ov else None), nv.value
        reason = nv.reason or (ov.reason if ov else "MISSING_INPUT")
        changes.append(
            MetricChange(
                name,
                nv.basis,
                o,
                n,
                None if o is None or n is None else n - o,
                "difference",
                None if o is not None and n is not None else reason,
            )
        )
    for name, entry in new.levels.items():
        for basis in ("ytd", "quarter", "ttm"):
            nval = entry[basis].value
            prev = old.levels.get(name, {}).get(basis)
            pval = prev.value if prev is not None else None
            g, why = growth(nval, pval)
            changes.append(MetricChange(name, basis, pval, nval, g, "relative", why))
    warn = new.tms29_applies and min(old.report.period_end, new.report.period_end) < tms29_consistent_from
    warnings: list[WarningItem] = []
    if warn:
        warnings.append(
            WarningItem(
                code=WarningCode.TMS29_WARNING,
                severity=Severity.SOFT,
                detail=f"comparison {old.report.fiscal_period} -> {new.report.fiscal_period} reaches before "
                f"{tms29_consistent_from}: reports are in different purchasing power (TMS 29)",
                ticker=new.report.ticker,
            )
        )
    if not new.tms29_applies:
        warnings.append(
            WarningItem(
                code=WarningCode.NOMINAL_VALUES,
                severity=Severity.INFO,
                detail=f"{new.report.ticker} does not apply TMS 29: TRY growth is nominal (includes inflation/FX)",
                ticker=new.report.ticker,
            )
        )
    return FundamentalChange(
        new.report.ticker, old.report.fiscal_period, new.report.fiscal_period, changes, warn, warnings
    )


# ----------------------------------------------------------------------------------------------- reactions
@dataclass(frozen=True)
class BaseDay:
    disclosure_datetime: str
    base_day: date | None
    timing: str  # after_close | before_or_during_session | non_trading_day | time_unknown
    warning: WarningItem | None


def reaction_base_day(disclosure_datetime: str, calendar: TradingCalendar, *, close_time: str = "18:10") -> BaseDay:
    s = disclosure_datetime.strip()
    d = date.fromisoformat(s[:10])
    tm: time | None = datetime.strptime(s[11:19], "%H:%M:%S").time() if len(s) >= 19 else None
    if tm == time(0, 0, 0):
        tm = None
    days = list(calendar.days)
    before = [x for x in days if x < d]
    prev_day = before[-1] if before else None
    warning = None
    if tm is None:
        timing = "time_unknown"
        warning = WarningItem(
            code=WarningCode.DISCLOSURE_TIME_UNKNOWN,
            severity=Severity.SOFT,
            detail=f"disclosure {s}: time of day unknown, treated as after the close",
        )
        base = d if calendar.is_trading_day(d) else prev_day
    elif not calendar.is_trading_day(d):
        timing, base = "non_trading_day", prev_day
    elif tm > time.fromisoformat(close_time):
        timing, base = "after_close", d
    else:
        timing, base = "before_or_during_session", prev_day
    return BaseDay(s, base, timing, warning)


@dataclass
class ReactionStudy:
    ticker: str
    table: pd.DataFrame  # one row per (report, horizon): fiscal_period, disclosure, base_day, timing, ret, abn_*
    excluded: list[ExcludedEvent]
    warnings: list[WarningItem]


def post_disclosure_reactions(
    reports: Sequence[Report],
    close: pd.Series,
    calendar: TradingCalendar,
    *,
    horizons: Sequence[int] = (1, 3, 5, 10, 20),
    benchmark: pd.Series | None = None,
    peers: pd.DataFrame | None = None,
    close_time: str = "18:10",
) -> ReactionStudy:
    rows: list[pd.DataFrame] = []
    excluded: list[ExcludedEvent] = []
    warnings: list[WarningItem] = []
    cal = CalendarIndex(calendar)
    for rep in sorted(reports, key=lambda r: r.disclosure_datetime):
        bd = reaction_base_day(rep.disclosure_datetime, calendar, close_time=close_time)
        if bd.warning is not None:
            warnings.append(bd.warning.model_copy(update={"ticker": rep.ticker}))
        if bd.base_day is None or cal.position(bd.base_day) is None:
            continue
        out = event_outcomes(
            [bd.base_day],
            close,
            calendar,
            horizons,
            direction=Direction.BULLISH,
            benchmark=benchmark,
            peers=peers,
            event_type=f"DISCLOSURE {rep.fiscal_period}",
            ticker=rep.ticker,
        )
        excluded.extend(out.excluded)
        t = out.table.drop(columns=["mfe"]).copy()
        t.insert(0, "timing", bd.timing)
        t.insert(0, "disclosure_index", rep.disclosure_index)
        t.insert(0, "disclosure_datetime", rep.disclosure_datetime)
        t.insert(0, "fiscal_period", rep.fiscal_period)
        rows.append(t)
    table = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return ReactionStudy(reports[0].ticker if reports else "", table, excluded, warnings)


def group_reactions(
    table: pd.DataFrame, labels: Mapping[str, str], *, horizon: int, value: str = "abn_benchmark"
) -> dict[str, stats.Summary | stats.TestResult]:
    """Reactions grouped by a label per fiscal period (e.g. 'improved' / 'deteriorated' revenue growth, or the
    technical state on the base day); Welch test between the first two groups in sorted order."""
    sub = table[table["horizon"] == horizon]
    sub = sub.assign(group=sub["fiscal_period"].map(labels)).dropna(subset=["group"])
    out: dict[str, stats.Summary | stats.TestResult] = {}
    names = sorted(sub["group"].unique())
    for g in names:
        out[g] = stats.summarize(sub.loc[sub["group"] == g, value].to_numpy(dtype=float))
    if len(names) >= 2:
        a = sub.loc[sub["group"] == names[0], value].to_numpy(dtype=float)
        b = sub.loc[sub["group"] == names[1], value].to_numpy(dtype=float)
        out["welch"] = stats.welch_t_test(a, b)
    return out
