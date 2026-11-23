"""get_fundamental_metrics and calculate_fundamental_change — Scenario 4 (quarterly fundamentals & price reaction)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from pydantic import Field

from bistharness.analytics import fundamentals as fa
from bistharness.analytics import series
from bistharness.core import formatting as fmt
from bistharness.core.config import Instrument
from bistharness.core.enums import Severity, ToolStatus, WarningCode
from bistharness.core.schemas import WarningItem
from bistharness.tools import common
from bistharness.tools.base import ToolContext, ToolInput, ToolOutput, tool, warn

SOURCES = ("fundamentals", "prices")
TR_METRIC = {
    "revenue": "hasılat",
    "gross_profit": "brüt kâr",
    "ebitda": "FAVÖK",
    "operating_profit": "esas faaliyet kârı",
    "net_income_parent": "ana ortaklık net kârı",
    "operating_cash_flow": "işletme faaliyet nakit akışı",
    "net_interest_income": "net faiz geliri",
    "net_fee_commission_income": "net ücret ve komisyon geliri",
    "gross_written_premiums": "brüt yazılan prim",
    "technical_balance": "teknik kâr",
    "gross_margin": "brüt kâr marjı",
    "ebitda_margin": "FAVÖK marjı",
    "operating_margin": "esas faaliyet marjı",
    "net_margin": "net kâr marjı",
    "roe": "özkaynak kârlılığı (ROE)",
    "roa": "aktif kârlılığı (ROA)",
    "net_debt": "net borç",
    "net_debt_to_ebitda": "Net Borç/FAVÖK",
    "debt_to_equity": "finansal borç/özkaynak",
    "current_ratio": "cari oran",
    "quick_ratio": "likidite oranı",
    "cash_conversion": "nakit dönüşüm oranı",
    "loans_to_deposits": "kredi/mevduat oranı",
    "equity_to_assets": "özkaynak/aktif",
    "cost_to_income": "gider/gelir oranı",
    "pe": "F/K",
    "pb": "PD/DD",
    "ev_to_ebitda": "FD/FAVÖK",
}
KEY_RATIOS = {
    "tfrs": ("ebitda_margin", "net_margin", "roe", "net_debt_to_ebitda", "debt_to_equity", "current_ratio"),
    "bank": ("roe", "roa", "cost_to_income", "loans_to_deposits"),
    "insurance": ("roe", "roa"),
}


class FundamentalInput(ToolInput):
    ticker: str
    start: date | None = None
    end: date | None = None


class FundamentalChangeInput(ToolInput):
    ticker: str
    start: date | None = None
    end: date | None = None
    horizons: list[int] = Field(default_factory=lambda: [1, 5, 20])


def period_tr(fp: str) -> str:
    return f"{fp[:4]}Ç{fp[5]}"


def show(mv: fa.MetricValue, *, signed: bool = False) -> str:
    if mv.value is None:
        return "-"
    if mv.unit == "TRY":
        return fmt.try_amount(mv.value)
    if mv.unit == "ratio":
        return fmt.pct(mv.value, signed=signed)
    return fmt.multiple(mv.value)


def _rows(ctx: ToolContext, ticker: str, as_of: date) -> pd.DataFrame:
    return ctx.repo.fundamentals(ticker, as_of=as_of, role=None, latest_only=False).data


def _disclosed(rep: fa.Report) -> date:
    return date.fromisoformat(rep.disclosure_datetime[:10])


def _context_warnings(ctx: ToolContext, inst: Instrument, reps: list[fa.Report], as_of: date) -> list[WarningItem]:
    out: list[WarningItem] = []
    cons = date.fromisoformat(str(ctx.settings.raw["tms29"]["consistent_from"]))
    if inst.tms29_applies and any(r.period_end < cons for r in reps):
        out.append(
            warn(
                WarningCode.TMS29_WARNING,
                f"{inst.ticker}: reports ending before {cons} are in a different "
                "purchasing power (TMS 29); compare within 2025+ or same-report columns",
                ticker=inst.ticker,
            )
        )
    if not inst.tms29_applies:
        out.append(
            warn(
                WarningCode.NOMINAL_VALUES,
                f"{inst.ticker} does not apply TMS 29: TRY growth is nominal",
                severity=Severity.INFO,
                ticker=inst.ticker,
            )
        )
    end = ctx.repo.meta("fundamentals_coverage_end")
    if end and as_of.isoformat() > end[:10]:
        out.append(
            warn(
                WarningCode.FUNDAMENTALS_COVERAGE_END,
                f"KAP snapshot ends at {end}: later reports are not in the data",
                severity=Severity.INFO,
                ticker=inst.ticker,
            )
        )
    if reps:
        issues = ctx.repo.fundamental_issues(inst.ticker, as_of=as_of)
        idx = {r.disclosure_index for r in reps}
        for _, row in issues[issues["disclosure_index"].isin(idx)].iterrows():
            out.append(
                warn(
                    WarningCode(row["code"]),
                    f"KAP {row['disclosure_index']}: {row['detail']}",
                    severity=Severity(row["severity"]),
                    ticker=inst.ticker,
                )
            )
    return out


def _no_data(inst: Instrument, as_of: date) -> ToolOutput:
    w = warn(
        WarningCode.FUNDAMENTAL_REPORT_UNUSABLE,
        f"{inst.ticker}: no KAP financial report in the snapshot up to {as_of}",
        ticker=inst.ticker,
    )
    return ToolOutput({"ticker": inst.ticker, "reports": []}, [w], status=ToolStatus.INSUFFICIENT_DATA)


@tool(
    "get_fundamental_metrics",
    version="1.0.0",
    input_model=FundamentalInput,
    sources=SOURCES,
    description="Point-in-time KAP fundamentals of the latest report disclosed by the window end (growth, margins, "
    "ROE/ROA, leverage, liquidity, cash conversion, valuation at the window end) plus the report history; template "
    "rules (banks/insurers) and TMS 29 warnings.",
)
def get_fundamental_metrics(ctx: ToolContext, inp: FundamentalInput) -> ToolOutput:
    inst = common.instrument(ctx, inp.ticker, kind="stock")
    w = common.window(ctx, inp.start, inp.end, inp.as_of_date)
    reports = fa.build_reports(_rows(ctx, inst.ticker, w.end), ticker=inst.ticker)
    if not reports:
        return _no_data(inst, w.end)
    latest = reports[max(reports)]
    rm = fa.report_metrics(latest, reports, template=inst.template, tms29_applies=inst.tms29_applies)
    prices, pw = common.load_prices(ctx, [inst.ticker], w.end)
    raw = common.raw_close(prices, inst.ticker)
    val = fa.valuation(
        rm,
        reports,
        day=raw.index[-1].date(),
        raw_close=float(raw.iloc[-1]),
        actions=ctx.repo.corporate_actions(inst.ticker, as_of=w.end),
    )
    fmt_name = fa.statement_format(inst.template)
    history = []
    in_window = [
        r for r in sorted(reports.values(), key=lambda r: r.fiscal_period) if w.start <= _disclosed(r) <= w.end
    ]
    for r in in_window:
        hm = fa.report_metrics(r, reports, template=inst.template, tms29_applies=inst.tms29_applies)
        history.append(
            {
                "fiscal_period": r.fiscal_period,
                "disclosure_datetime": r.disclosure_datetime,
                "disclosure_index": r.disclosure_index,
                "tms29_adjusted": r.tms29_adjusted,
                "n_versions": r.n_versions,
                "yoy_ytd": {k: v["yoy_ytd"].value for k, v in hm.levels.items()},
                "ratios": {k: hm.ratios[k].value for k in KEY_RATIOS[fmt_name] if k in hm.ratios},
            }
        )
    warnings = pw + rm.warnings + _context_warnings(ctx, inst, [latest, *in_window], w.end)
    if val.share_count_approx:
        warnings.append(
            warn(
                WarningCode.SHARE_COUNT_APPROX,
                "rights issue after the report: share count approximate",
                ticker=inst.ticker,
            )
        )
    result: dict[str, Any] = {
        "ticker": inst.ticker,
        "template": inst.template,
        "statement_format": fmt_name,
        "tms29_applies": inst.tms29_applies,
        "latest_report": {
            "fiscal_period": latest.fiscal_period,
            "period_end": latest.period_end,
            "disclosure_datetime": latest.disclosure_datetime,
            "disclosure_index": latest.disclosure_index,
            "scope": latest.scope,
            "tms29_adjusted": latest.tms29_adjusted,
            "n_versions": latest.n_versions,
            "source": f"https://www.kap.org.tr/tr/Bildirim/{latest.disclosure_index}",
        },
        "levels": rm.levels,
        "ratios": rm.ratios,
        "valuation": val,
        "history": history,
    }
    ev = []
    base = {
        "ticker": inst.ticker,
        "fp": period_tr(latest.fiscal_period),
        "dt": fmt.tr_datetime(latest.disclosure_datetime),
    }
    ev.append(
        common.evidence(
            f"fundamentals.{inst.ticker}.latest_report",
            "{ticker} için {fp} dönemi finansal raporu KAP'ta {dt} tarihinde yayımlandı; analiz yalnız bu tarihe kadar "
            "açıklanmış verileri kullanır.",
            base,
            values={"disclosure_index": latest.disclosure_index},
            pointer="/result/latest_report",
            primary=True,
        )
    )
    top = fa.LEVEL_METRICS[fmt_name][0]
    for m in (top, "ebitda", "net_income_parent"):
        if m not in rm.levels:
            continue
        g, lvl = rm.levels[m]["yoy_ytd"], rm.levels[m]["ytd"]
        if g.value is None or lvl.value is None:
            continue
        disp = {
            **base,
            "metric": TR_METRIC[m],
            "val": show(lvl),
            "g": show(g, signed=True),
            "dir": common.direction(g.value, up="artış", down="düşüş", flat="değişim yok"),
        }
        ev.append(
            common.evidence(
                f"fundamentals.{inst.ticker}.{m}.yoy_ytd",
                "{ticker} {fp} yılbaşından bu yana {metric} {val}; aynı rapordaki geçen yıl tutarına göre değişim {g} ({dir}).",
                disp,
                values={"value": lvl.value, "yoy": g.value},
                pointer=f"/result/levels/{m}",
                primary=True,
            )
        )
    for k in KEY_RATIOS[fmt_name]:
        mv = rm.ratios.get(k)
        if mv is None:
            continue
        if mv.value is None:
            if mv.reason == WarningCode.NOT_APPLICABLE_FOR_TEMPLATE:
                ev.append(
                    common.evidence(
                        f"fundamentals.{inst.ticker}.{k}.not_applicable",
                        "{metric} bu şirketin şablonunda ({tmpl}) hesaplanmaz.",
                        {"metric": TR_METRIC[k], "tmpl": inst.template.value},
                        pointer=f"/result/ratios/{k}",
                        kind="warning",
                    )
                )
            continue
        disp = {**base, "metric": TR_METRIC[k], "val": show(mv)}
        ev.append(
            common.evidence(
                f"fundamentals.{inst.ticker}.{k}",
                "{ticker} {fp} itibarıyla {metric}: {val}.",
                disp,
                values={"value": mv.value, "approx": mv.approx},
                pointer=f"/result/ratios/{k}",
                primary=k in ("ebitda_margin", "roe", "net_debt_to_ebitda", "cost_to_income"),
            )
        )
    for k, mv in val.metrics.items():
        if mv.value is None:
            continue
        disp = {**base, "metric": TR_METRIC[k], "val": show(mv), "day": fmt.tr_date(val.day), "px": fmt.num(val.price)}
        ev.append(
            common.evidence(
                f"fundamentals.{inst.ticker}.valuation.{k}",
                "{day} kapanışı ({px} TL) ve {fp} raporuyla {metric}: {val}.",
                disp,
                values={"value": mv.value, "price": val.price, "shares": val.shares},
                pointer=f"/result/valuation/metrics/{k}",
                primary=k in ("pe", "pb"),
            )
        )
    return ToolOutput(result, warnings, evidence=ev)


# ----------------------------------------------------------------------------------------------- change + reaction
def _change_summary(old: fa.ReportMetrics | None, new: fa.ReportMetrics, fmt_name: str, cons: date) -> dict[str, Any]:
    out: dict[str, Any] = {
        "yoy_ytd": {k: v["yoy_ytd"].value for k, v in new.levels.items()},
        "qoq": {k: v["qoq"].value for k, v in new.levels.items()},
    }
    if old is not None:
        ch = fa.compare_reports(old, new, tms29_consistent_from=cons)
        out["ratio_changes"] = {
            c.name: {"old": c.old, "new": c.new, "change": c.change}
            for c in ch.changes
            if c.kind == "difference" and c.name in KEY_RATIOS[fmt_name]
        }
        out["tms29_warning"] = ch.tms29_warning
    return out


@tool(
    "calculate_fundamental_change",
    version="1.0.0",
    input_model=FundamentalChangeInput,
    sources=SOURCES,
    description="Scenario 4: for every KAP report disclosed in the window, QoQ/YoY changes (margins, leverage, ROE) "
    "computed with the reports known at that disclosure, valuation before/after, and the post-disclosure 1/5/20-day "
    "return and abnormal return vs XU100 and the sector basket (incomplete windows listed, never dropped).",
)
def calculate_fundamental_change(ctx: ToolContext, inp: FundamentalChangeInput) -> ToolOutput:
    inst = common.instrument(ctx, inp.ticker, kind="stock")
    w = common.window(ctx, inp.start, inp.end, inp.as_of_date)
    sp = common.study_params(ctx, inp.horizons)
    rows = _rows(ctx, inst.ticker, w.as_of)
    all_reports = fa.build_reports(rows, ticker=inst.ticker)
    window_reps = [
        r for r in sorted(all_reports.values(), key=lambda r: r.fiscal_period) if w.start <= _disclosed(r) <= w.end
    ]
    if not window_reps:
        return _no_data(inst, w.end)
    fmt_name = fa.statement_format(inst.template)
    cons = date.fromisoformat(str(ctx.settings.raw["tms29"]["consistent_from"]))
    peers = common.peers_of(ctx, inst.ticker)
    bench = ctx.universe.benchmark
    prices, warnings = common.load_prices(ctx, [inst.ticker, bench], w.as_of, optional=peers)
    peers = common.available(prices, peers)
    close = common.ohlcv(prices, inst.ticker)["close"]
    raw = common.raw_close(prices, inst.ticker)
    xu = common.ohlcv(prices, bench)["close"]
    peer_closes = series.column_matrix(prices, peers) if peers else None
    cal = common.calendar(ctx, w.as_of)
    actions = ctx.repo.corporate_actions(inst.ticker, as_of=w.as_of)
    react = fa.post_disclosure_reactions(
        window_reps,
        close,
        cal,
        horizons=sp.horizons,
        benchmark=xu,
        peers=peer_closes,
        close_time=str(ctx.settings.raw["session"]["close_time"]),
    )
    warnings += react.warnings
    per_report: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    for rep in window_reps:
        known = fa.build_reports(rows[rows["disclosure_datetime"] <= rep.disclosure_datetime], ticker=inst.ticker)
        new = fa.report_metrics(
            known[rep.fiscal_period], known, template=inst.template, tms29_applies=inst.tms29_applies
        )
        prev_rep = known.get(fa.shift_period(rep.fiscal_period, -1))
        old = (
            fa.report_metrics(prev_rep, known, template=inst.template, tms29_applies=inst.tms29_applies)
            if prev_rep is not None
            else None
        )
        bd = fa.reaction_base_day(
            rep.disclosure_datetime, cal, close_time=str(ctx.settings.raw["session"]["close_time"])
        )
        entry: dict[str, Any] = {
            "fiscal_period": rep.fiscal_period,
            "disclosure_datetime": rep.disclosure_datetime,
            "disclosure_index": rep.disclosure_index,
            "base_day": bd.base_day,
            "timing": bd.timing,
            **_change_summary(old, new, fmt_name, cons),
        }
        if bd.base_day is not None and pd.Timestamp(bd.base_day) in raw.index:
            px = float(raw.loc[pd.Timestamp(bd.base_day)])
            entry["valuation_before"] = (
                fa.valuation(old, known, day=bd.base_day, raw_close=px, actions=actions).metrics
                if old is not None
                else None
            )
            entry["valuation_after"] = fa.valuation(new, known, day=bd.base_day, raw_close=px, actions=actions).metrics
        sub = (
            react.table[react.table["disclosure_index"] == rep.disclosure_index]
            if not react.table.empty
            else react.table
        )
        entry["reaction"] = {
            int(r.horizon): {
                "end_date": r.end_date,
                "ret": r.ret,
                "abn_xu100": r.abn_benchmark,
                "abn_sector": r.abn_peers,
            }
            for r in sub.itertuples()
        }
        per_report.append(entry)
        if fmt_name == "tfrs":
            ch = entry.get("ratio_changes", {}).get("ebitda_margin", {}).get("change")
            if ch is not None:
                labels[rep.fiscal_period] = "improved" if ch > 0 else "deteriorated"
        else:
            g = entry["yoy_ytd"].get("net_income_parent")
            if g is not None:
                labels[rep.fiscal_period] = "improved" if g > 0 else "deteriorated"
        if entry.get("tms29_warning"):
            warnings.append(
                warn(
                    WarningCode.TMS29_WARNING,
                    f"{rep.fiscal_period} vs previous report spans before {cons}",
                    ticker=inst.ticker,
                )
            )
        warnings += [x for x in new.warnings if x.code == WarningCode.TMS29_DECUMULATION_APPROX]
    warnings += _context_warnings(ctx, inst, window_reps, w.as_of)
    aggregate: dict[int, Any] = {}
    t = react.table
    for h in sp.horizons:
        sub = t[t["horizon"] == h] if not t.empty else t
        aggregate[h] = {
            "n": len(sub),
            "mean_ret": sub["ret"].mean() if len(sub) else None,
            "mean_abn_xu100": sub["abn_benchmark"].mean() if len(sub) else None,
            "median_abn_xu100": sub["abn_benchmark"].median() if len(sub) else None,
            "mean_abn_sector": sub["abn_peers"].mean() if len(sub) and sub["abn_peers"].notna().any() else None,
        }
    main_h = max(sp.horizons)
    by_dir = fa.group_reactions(t, labels, horizon=main_h) if not t.empty and labels else {}
    result: dict[str, Any] = {
        "ticker": inst.ticker,
        "template": inst.template,
        "tms29_applies": inst.tms29_applies,
        "start": w.start,
        "end": w.end,
        "horizons": sp.horizons,
        "peers": peers,
        "label_rule": "improved = EBITDA margin up vs previous report"
        if fmt_name == "tfrs"
        else "improved = YTD net income up vs prior year (same report)",
        "reports": per_report,
        "aggregate": aggregate,
        "by_change_direction": {"horizon": main_h, "groups": by_dir},
    }
    ev = _change_evidence(inst, per_report, aggregate, by_dir, main_h, react.excluded, w.as_of)
    return ToolOutput(result, warnings, excluded=react.excluded, evidence=ev)


def _change_evidence(
    inst: Instrument,
    per_report: list[dict[str, Any]],
    aggregate: dict[int, Any],
    by_dir: dict[str, Any],
    main_h: int,
    excluded: list[Any],
    as_of: date,
) -> list[Any]:
    ev = []
    last = per_report[-1]
    base = {
        "ticker": inst.ticker,
        "fp": period_tr(last["fiscal_period"]),
        "dt": fmt.tr_datetime(last["disclosure_datetime"]),
    }
    for k, c in last.get("ratio_changes", {}).items():
        if c["change"] is None or k not in (
            "ebitda_margin",
            "net_debt_to_ebitda",
            "roe",
            "net_margin",
            "cost_to_income",
        ):
            continue
        is_ratio = k not in ("net_debt_to_ebitda",)
        disp = {
            **base,
            "metric": TR_METRIC[k],
            "old": fmt.pct(c["old"]) if is_ratio else fmt.multiple(c["old"]),
            "new": fmt.pct(c["new"]) if is_ratio else fmt.multiple(c["new"]),
            "chg": fmt.pp_from_fraction(c["change"]) if is_ratio else fmt.num(c["change"]),
            "dir": common.direction(c["change"]),
        }
        ev.append(
            common.evidence(
                f"fundamental_change.{inst.ticker}.{last['fiscal_period']}.{k}",
                "{ticker} {fp} raporunda {metric} önceki rapordaki {old} değerinden {new} değerine {dir} ({chg}).",
                disp,
                values=c,
                pointer=f"/result/reports/{len(per_report) - 1}/ratio_changes/{k}",
                primary=True,
            )
        )
    for h, r in sorted(last.get("reaction", {}).items()):
        disp = {
            **base,
            "h": str(h),
            "ret": fmt.pct(r["ret"], signed=True),
            "abn": fmt.pp_from_fraction(r["abn_xu100"]) if r["abn_xu100"] is not None else "-",
            "sec": fmt.pp_from_fraction(r["abn_sector"]) if r["abn_sector"] is not None else "-",
            "end": fmt.tr_date(r["end_date"]),
        }
        ev.append(
            common.evidence(
                f"fundamental_change.{inst.ticker}.{last['fiscal_period']}.reaction.h{h}",
                "{ticker} {fp} raporunun ({dt}) ardından {h} işlem günlük getiri {ret} ({end}); XU100'e "
                "göre fark {abn}, sektör sepetine göre {sec}.",
                disp,
                values=r,
                pointer=f"/result/reports/{len(per_report) - 1}/reaction/{h}",
                primary=True,
            )
        )
    a = aggregate.get(main_h)
    if a and a["n"]:
        disp = {
            "ticker": inst.ticker,
            "n": fmt.integer(a["n"]),
            "h": str(main_h),
            "abn": fmt.pp_from_fraction(a["mean_abn_xu100"]),
            "med": fmt.pp_from_fraction(a["median_abn_xu100"]),
        }
        ev.append(
            common.evidence(
                f"fundamental_change.{inst.ticker}.aggregate.h{main_h}",
                "{ticker} için {n} rapor açıklamasının ardından {h} günlük XU100'e göre ortalama anormal "
                "getiri {abn} (medyan {med}).",
                disp,
                values=a,
                pointer=f"/result/aggregate/{main_h}",
                kind="statistic",
                primary=True,
            )
        )
    if "improved" in by_dir and "deteriorated" in by_dir:
        imp, det = by_dir["improved"], by_dir["deteriorated"]
        disp = {
            "h": str(main_h),
            "ni": fmt.integer(imp.n),
            "nd": fmt.integer(det.n),
            "mi": fmt.pp_from_fraction(imp.mean) if imp.mean is not None else "-",
            "md": fmt.pp_from_fraction(det.mean) if det.mean is not None else "-",
        }
        ev.append(
            common.evidence(
                f"fundamental_change.{inst.ticker}.by_direction.h{main_h}",
                "İyileşen raporlardan sonra {h} günlük ortalama anormal getiri {mi} ({ni} rapor), "
                "kötüleşenlerden sonra {md} ({nd} rapor).",
                disp,
                values={
                    "improved_n": imp.n,
                    "deteriorated_n": det.n,
                    "improved_mean": imp.mean,
                    "deteriorated_mean": det.mean,
                },
                pointer="/result/by_change_direction",
                kind="statistic",
                primary=True,
            )
        )
    for e in excluded:
        disp = {
            "ticker": inst.ticker,
            "d": fmt.tr_date(e.event_date),
            "h": str(e.horizon),
            "avail": fmt.integer(e.trading_days_available),
            "asof": fmt.tr_date(as_of),
        }
        ev.append(
            common.evidence(
                f"fundamental_change.{inst.ticker}.excluded.{e.event_date}.h{e.horizon}",
                "{ticker} için {d} baz günlü açıklamanın {h} günlük penceresi {asof} itibarıyla tamamlanmadı "
                "({avail} işlem günü var); bu ufuk istatistiğe alınmadı.",
                disp,
                values={"trading_days_available": e.trading_days_available},
                pointer="/excluded_incomplete_events",
                kind="warning",
                primary=True,
            )
        )
    return ev
