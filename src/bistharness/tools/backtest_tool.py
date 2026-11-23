"""run_backtest — strategy variants A-E with t+1 execution, costs, benchmarks and in/out-of-sample metrics.

Every read uses as_of = the backtest window end, so no information after the window can reach any decision; inside
the window each day's masks only use information known by that day (backtest/strategies.py).
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import pandas as pd
from pydantic import Field

from bistharness.analytics import events, indicators, macro_stats, series
from bistharness.backtest import strategies
from bistharness.backtest.engine import CostModel, buy_and_hold_returns, simulate
from bistharness.backtest.metrics import daily_risk_free, real_return, return_metrics, trade_stats
from bistharness.core import formatting as fmt
from bistharness.core.enums import Severity, WarningCode
from bistharness.tools import common
from bistharness.tools.base import ToolContext, ToolInput, ToolInputError, ToolOutput, tool, warn


class BacktestInput(ToolInput):
    strategy_spec: dict[str, Any] = Field(default_factory=dict)
    universe: str | list[str] = "course_30"
    start: date | None = None
    end: date | None = None
    variant: str = "ALL"
    tx_cost_bps: float = Field(default=10.0, ge=0, le=500)
    slippage_bps: float = Field(default=0.0, ge=0, le=500)
    split_date: date | None = None
    max_trades_listed: int = Field(default=100, ge=0, le=2000)
    include_equity: bool = False


def _universe(ctx: ToolContext, spec: str | list[str]) -> list[str]:
    if isinstance(spec, list):
        return [common.instrument(ctx, t, kind="stock").ticker for t in spec]
    if spec in ctx.universe.universes:
        return list(ctx.universe.tickers(spec))
    return [common.instrument(ctx, spec, kind="stock").ticker]


def _spec(raw: dict[str, Any]) -> strategies.StrategySpec:
    names = {f.name for f in dataclasses.fields(strategies.StrategySpec)}
    bad = sorted(set(raw) - names)
    if bad:
        raise ToolInputError(f"unknown strategy_spec fields {bad}; allowed: {sorted(names)}")

    def tup(x: Any) -> Any:
        return tuple(tup(i) for i in x) if isinstance(x, list | tuple) else x

    vals: dict[str, Any] = {k: tup(v) for k, v in raw.items()}
    try:
        spec: strategies.StrategySpec = dataclasses.replace(strategies.StrategySpec(), **vals)
        return spec
    except (TypeError, ValueError) as exc:
        raise ToolInputError(str(exc)) from exc


@tool(
    "run_backtest",
    version="1.0.0",
    input_model=BacktestInput,
    sources=("prices", "fundamentals", "macro", "news"),
    description="Backtests the educational long-only strategy variants A_TECH, B_TECH_SECTOR, C_TECH_SECTOR_FUND, "
    "D_FULL_STRUCTURED, E_FULL_CONTEXTUAL (signal at close t, trade at t+1 open, costs+slippage) against "
    "buy-and-hold, XU100 and the sector basket: cumulative (nominal and CPI-real) return, Sharpe (rf=0 and TCMB "
    "policy rate), max drawdown, win rate, number of signals, in/out-of-sample split. BUY/SELL are backtest labels only.",
)
def run_backtest(ctx: ToolContext, inp: BacktestInput) -> ToolOutput:
    variants = list(strategies.VARIANTS) if inp.variant == "ALL" else [inp.variant]
    if any(v not in strategies.VARIANTS for v in variants):
        raise ToolInputError(f"variant must be ALL or one of {strategies.VARIANTS}")
    spec = _spec(inp.strategy_spec)
    tickers = _universe(ctx, inp.universe)
    w = common.window(ctx, inp.start, inp.end, inp.as_of_date)
    if inp.split_date is not None and not (w.start < inp.split_date <= w.end):
        raise ToolInputError("split_date must lie inside the backtest window")
    end = w.end  # every read below uses as_of = end
    bench = ctx.universe.benchmark
    peer_union = sorted({p for t in tickers for p in ctx.universe.peers(t)} | set(tickers))
    prices, warnings = common.load_prices(ctx, [*tickers, bench], end, optional=peer_union)
    peer_union = common.available(prices, peer_union)
    cal = common.calendar(ctx, end)
    days_all = pd.DatetimeIndex([pd.Timestamp(d) for d in cal.days])
    days = days_all[days_all >= pd.Timestamp(w.start)]
    opens = series.column_matrix(prices, peer_union, "open")
    closes = series.column_matrix(prices, peer_union, "close")
    xu = common.ohlcv(prices, bench)["close"]

    flags, inds = {}, {}
    for t in tickers:
        ind = indicators.compute_indicators(common.ohlcv(prices, t))
        inds[t] = ind
        flags[t] = events.detect_events(ind)
    if spec.weekday_condition:
        tech = strategies.weekday_entries({t: inds[t]["close"] for t in tickers}, spec, days_all)
    else:
        tech = strategies.technical_entries(flags, inds, spec, days_all)
    needed = {layer for v in variants for layer in strategies.LAYERS[v]}
    masks: dict[str, pd.DataFrame] = {}
    if "sector" in needed:
        cols = {}
        for t in tickers:
            members = common.available(prices, ctx.universe.peers(t))
            if len(members) < 2:
                warnings.append(
                    warn(WarningCode.SMALL_SECTOR_GROUP, f"{t}: no peers -> sector layer never passes", ticker=t)
                )
            cols[t] = strategies.sector_mask(closes[members], t, cal, xu, spec)
        masks["sector"] = pd.DataFrame(cols).reindex(days_all).fillna(False).astype(bool)
    if "fundamental" in needed:
        cols = {}
        for t in tickers:
            rows = ctx.repo.fundamentals(t, as_of=end, role=None, latest_only=False).data
            tl = strategies.fundamental_timeline(rows, t, ctx.universe.instrument(t).template, spec)
            cols[t] = strategies.fundamental_mask(tl, days_all)
        masks["fundamental"] = pd.DataFrame(cols, index=days_all)
    macro_rows = ctx.repo.macro(["USDTRY", "TCMB_POLICY_RATE", "TUFE_MOM"], as_of=end).data
    if "macro" in needed:
        m = strategies.macro_mask(macro_rows, days_all, spec)
        masks["macro"] = pd.DataFrame({t: m for t in tickers}, index=days_all)
    if "news" in needed:
        cols = {}
        for t in tickers:
            nd = ctx.repo.news(as_of=end, ticker=t).data
            cols[t] = strategies.news_mask(nd, t, days_all, spec)
        masks["news"] = pd.DataFrame(cols, index=days_all)

    pr = macro_rows[macro_rows["series_code"] == "TCMB_POLICY_RATE"]
    policy = strategies.known_step(pr, days)
    rf = daily_risk_free(policy.dropna(), days)
    infl = macro_stats.inflation_between(macro_rows, w.start, w.end)
    bh = buy_and_hold_returns(closes[tickers], days)
    xu_r = buy_and_hold_returns(xu.to_frame("XU100"), days)
    sector_r = buy_and_hold_returns(closes[peer_union], days)
    bench_metrics = {
        "buy_and_hold": return_metrics(bh, rf),
        "xu100": return_metrics(xu_r, rf),
        "sector_basket": return_metrics(sector_r, rf),
    }
    costs = CostModel(inp.tx_cost_bps, inp.slippage_bps)
    small, insufficient = (
        int(ctx.settings.threshold("small_sample")),
        int(ctx.settings.threshold("insufficient_sample")),
    )
    out_variants: dict[str, Any] = {}
    ev = []
    for v in variants:
        combined = strategies.apply_variant(tech, masks, v)
        sig = strategies.signal_dates(combined, pd.Timestamp(w.start))
        sim = simulate(sig, opens, closes, days, holding_days=spec.holding_days, costs=costs, universe=tickers)
        met = return_metrics(sim.portfolio_returns, rf)
        ts = trade_stats(sim.trades)
        # same trades, but idle sleeve capital earns the TCMB policy rate known that day (money-market proxy)
        idle = 1 - sim.exposure.reindex(days).fillna(0.0)
        with_cash = sim.portfolio_returns + idle * rf.fillna(0.0)
        met_cash = return_metrics(with_cash, rf)
        block: dict[str, Any] = {
            "layers": strategies.LAYERS[v],
            "metrics": met,
            "real_cumulative": real_return(met.cumulative, infl.cumulative),
            "cash_at_policy_rate": {
                "metrics": met_cash,
                "real_cumulative": real_return(met_cash.cumulative, infl.cumulative),
            },
            "trades": ts,
            "exposure_mean": float(sim.exposure.mean()) if len(sim.exposure) else None,
            "skipped_signals": sim.skipped_signals,
            "pending_signals": [{"ticker": t, "signal_date": d} for t, d in sim.pending_signals],
            "vs_xu100": None
            if met.cumulative is None or bench_metrics["xu100"].cumulative is None
            else met.cumulative - bench_metrics["xu100"].cumulative,
            "vs_buy_and_hold": None
            if met.cumulative is None or bench_metrics["buy_and_hold"].cumulative is None
            else met.cumulative - bench_metrics["buy_and_hold"].cumulative,
            "trade_list": [dataclasses.asdict(t) for t in sim.trades[-inp.max_trades_listed :]]
            if inp.max_trades_listed
            else [],
        }
        if inp.include_equity:
            eq = pd.DataFrame(
                {
                    "strategy": (1 + sim.portfolio_returns).cumprod() - 1,
                    "xu100": (1 + xu_r).cumprod() - 1,
                    "buy_and_hold": (1 + bh).cumprod() - 1,
                }
            )
            block["equity"] = eq.reset_index().rename(columns={"index": "date"})
        if inp.split_date is not None:
            sd = pd.Timestamp(inp.split_date)
            pr_ = sim.portfolio_returns
            block["in_sample"] = return_metrics(pr_[pr_.index < sd], rf)
            block["out_of_sample"] = return_metrics(pr_[pr_.index >= sd], rf)
            block["in_sample_trades"] = trade_stats([t for t in sim.trades if t.signal_date < sd])
            block["out_of_sample_trades"] = trade_stats([t for t in sim.trades if t.signal_date >= sd])
        out_variants[v] = block
        if ts.n_closed < insufficient:
            warnings.append(warn(WarningCode.INSUFFICIENT_SAMPLE, f"{v}: {ts.n_closed} closed trades"))
        elif ts.n_closed < small:
            warnings.append(warn(WarningCode.SMALL_SAMPLE, f"{v}: {ts.n_closed} closed trades"))
        if met.cumulative is None:
            continue
        disp = {
            "v": v,
            "s": fmt.tr_date(w.start),
            "e": fmt.tr_date(w.end),
            "n": fmt.integer(ts.n_closed),
            "win": fmt.pct(ts.win_rate) if ts.win_rate is not None else "-",
            "cum": fmt.pct(met.cumulative, signed=True),
            "xu": fmt.pct(bench_metrics["xu100"].cumulative or 0.0, signed=True),
            "bh": fmt.pct(bench_metrics["buy_and_hold"].cumulative or 0.0, signed=True),
            "sh": fmt.num(met.sharpe_rf0) if met.sharpe_rf0 is not None else "-",
            "shp": fmt.num(met.sharpe_policy) if met.sharpe_policy is not None else "-",
            "mdd": fmt.pct(met.max_drawdown or 0.0),
            "bps": fmt.num(inp.tx_cost_bps + inp.slippage_bps, 0),
            "real": fmt.pct(block["real_cumulative"], signed=True) if block["real_cumulative"] is not None else "-",
            "vs": common.direction(block["vs_xu100"], up="üzerinde", down="altında", flat="aynı seviyesinde"),
        }
        ev.append(
            common.evidence(
                f"backtest.{v}",
                "Varyant {v} ({s}–{e}, işlem başı {bps} baz puan maliyet): {n} kapanmış işlem, kazanan oranı {win}; "
                "kümülatif getiri {cum}, XU100'ün {vs} (TÜFE'ye göre reel {real}); XU100 {xu}, eşit ağırlıklı al-tut {bh}; "
                "Sharpe {sh} "
                "(politika faizine göre {shp}); en büyük düşüş {mdd}.",
                disp,
                values={
                    "n": ts.n_closed,
                    "cumulative": met.cumulative,
                    "win_rate": ts.win_rate,
                    "sharpe_rf0": met.sharpe_rf0,
                    "max_drawdown": met.max_drawdown,
                    "vs_xu100": block["vs_xu100"],
                },
                pointer=f"/result/variants/{v}",
                kind="statistic",
                primary=True,
            )
        )
        if met_cash.cumulative is not None:
            ev.append(
                common.evidence(
                    f"backtest.{v}.cash_at_policy_rate",
                    "Varyant {v}: boştaki nakit o gün geçerli TCMB politika faiziyle değerlendirilseydi kümülatif getiri "
                    "{cum} (TÜFE'ye göre reel {real}), politika faizine göre Sharpe {shp} olurdu.",
                    {
                        "v": v,
                        "cum": fmt.pct(met_cash.cumulative, signed=True),
                        "real": fmt.pct(block["cash_at_policy_rate"]["real_cumulative"], signed=True)
                        if block["cash_at_policy_rate"]["real_cumulative"] is not None
                        else "-",
                        "shp": fmt.num(met_cash.sharpe_policy) if met_cash.sharpe_policy is not None else "-",
                    },
                    values={"cumulative": met_cash.cumulative, "sharpe_policy": met_cash.sharpe_policy},
                    pointer=f"/result/variants/{v}/cash_at_policy_rate",
                    kind="statistic",
                )
            )
        if inp.split_date is not None and block["out_of_sample"].cumulative is not None:
            o, ot = block["out_of_sample"], block["out_of_sample_trades"]
            ev.append(
                common.evidence(
                    f"backtest.{v}.out_of_sample",
                    "Varyant {v} örneklem dışında ({sd} sonrası) {n} kapanmış işlem, kümülatif getiri {cum}, Sharpe {sh}.",
                    {
                        "v": v,
                        "sd": fmt.tr_date(inp.split_date),
                        "n": fmt.integer(ot.n_closed),
                        "cum": fmt.pct(o.cumulative, signed=True),
                        "sh": fmt.num(o.sharpe_rf0) if o.sharpe_rf0 is not None else "-",
                    },
                    values={"n": ot.n_closed, "cumulative": o.cumulative},
                    pointer=f"/result/variants/{v}/out_of_sample",
                    kind="statistic",
                    primary=True,
                )
            )
    if inp.strategy_spec:
        warnings.append(
            warn(
                WarningCode.MULTIPLE_TESTING_RISK,
                "custom strategy_spec: if it was chosen after seeing results, the backtest is data-mined",
                severity=Severity.INFO,
            )
        )
    if not infl.complete:
        warnings.append(
            warn(
                WarningCode.MISSING_MACRO,
                f"real return uses {infl.months_used}/{infl.months_expected} released CPI months",
                severity=Severity.INFO,
            )
        )
    result = {
        "universe": tickers,
        "start": w.start,
        "end": w.end,
        "strategy_spec": dataclasses.asdict(spec),
        "execution": "signal at close t (information <= t 23:59:59), entry at open t+1, exit at open after holding_days",
        "costs": dataclasses.asdict(costs),
        "benchmarks": bench_metrics,
        "inflation": infl,
        "variants": out_variants,
        "labels_note": "BUY/SELL exist only as educational backtest positions; no order is ever produced",
    }
    return ToolOutput(result, warnings, evidence=ev)
