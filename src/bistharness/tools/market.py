"""Market tools: get_stock_history, get_index_history, calculate_indicators, find_support_resistance."""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from pydantic import Field

from bistharness.analytics import event_study, events, indicators, support_resistance
from bistharness.backtest.metrics import max_drawdown
from bistharness.core import formatting as fmt
from bistharness.core.enums import Severity, WarningCode
from bistharness.core.schemas import WarningItem
from bistharness.tools import common
from bistharness.tools.base import ToolContext, ToolInput, ToolInputError, ToolOutput, tool, warn

PRICE_SOURCES = ("prices",)


class HistoryInput(ToolInput):
    ticker: str
    start: date | None = None
    end: date | None = None
    include_rows: bool = False


class IndexHistoryInput(ToolInput):
    index: str = "XU100"
    start: date | None = None
    end: date | None = None
    include_rows: bool = False


def _quality_warnings(ctx: ToolContext, ticker: str, w: common.Window) -> tuple[dict[str, int], list[WarningItem]]:
    flags = ctx.repo.quality_flags(ticker, w.start, w.end, as_of=w.as_of)
    counts = flags["code"].value_counts().sort_index().to_dict() if not flags.empty else {}
    out: list[WarningItem] = []
    for code, grp in flags.groupby("code", sort=True):
        sev = Severity(grp["severity"].iloc[0])
        dated = grp["date"].dropna()
        first = f", first {dated.min()}" if len(dated) else ""
        out.append(
            warn(WarningCode(code), f"{ticker}: {len(grp)} flag(s) in the window{first}", severity=sev, ticker=ticker)
        )
    return {str(k): int(v) for k, v in counts.items()}, out


def _history(
    ctx: ToolContext, ticker: str, start: date | None, end: date | None, as_of: date, include_rows: bool, kind: str
) -> ToolOutput:
    inst = common.instrument(ctx, ticker, kind=kind)
    w = common.window(ctx, start, end, as_of)
    pf = ctx.repo.prices(inst.ticker, w.start, w.end, as_of=as_of)
    df = pf.data
    warnings = list(pf.warnings)
    if df.empty:
        return ToolOutput({"ticker": inst.ticker, "n_days": 0}, warnings, status=common_status_insufficient())
    close = pd.Series(df["close"].to_numpy(dtype=float), index=pd.DatetimeIndex(df["date"]))
    ret = close.pct_change().dropna()
    period_return = float(close.iloc[-1] / close.iloc[0] - 1)
    actions = ctx.repo.corporate_actions(inst.ticker, as_of=as_of)
    actions = actions[(actions["ex_date"] >= w.start.isoformat()) & (actions["ex_date"] <= w.end.isoformat())]
    q_counts, q_warn = _quality_warnings(ctx, inst.ticker, w)
    warnings += q_warn
    result: dict[str, Any] = {
        "ticker": inst.ticker,
        "kind": inst.kind,
        "start": w.start,
        "end": w.end,
        "n_days": len(df),
        "first_date": close.index[0],
        "last_date": close.index[-1],
        "last_close": float(close.iloc[-1]),
        "last_raw_close": float(df["raw_close"].iloc[-1]),
        "period_return": period_return,
        "max_drawdown": max_drawdown(ret),
        "volatility_annualized": float(ret.std(ddof=1) * np.sqrt(252)) if len(ret) > 1 else None,
        "high": float(df["high"].max()),
        "low": float(df["low"].min()),
        "price_sources": df["price_source"].value_counts().sort_index().to_dict(),
        "corporate_actions": actions[["ex_date", "ratio", "kind", "source"]].to_dict("records"),
        "quality_flags": q_counts,
        "price_basis": "adjusted (splits + dividends) anchored at as_of; raw_* = printed prices",
    }
    if include_rows:
        result["rows"] = df[["date", "open", "high", "low", "close", "volume", "raw_close"]]
    disp = {
        "ticker": inst.ticker,
        "start": fmt.tr_date(close.index[0]),
        "end": fmt.tr_date(close.index[-1]),
        "ret": fmt.pct(period_return),
        "close": fmt.num(float(df["raw_close"].iloc[-1])),
        "unit": "TL" if inst.kind == "stock" else "puan",
        "mdd": fmt.pct(result["max_drawdown"]) if result["max_drawdown"] is not None else "-",
    }
    ev = [
        common.evidence(
            f"history.{inst.ticker}.period_return",
            "{ticker} {start}–{end} arasında düzeltilmiş kapanışa göre {ret} getiri sağladı (en büyük düşüş {mdd}).",
            disp,
            values={"period_return": period_return, "max_drawdown": result["max_drawdown"]},
            pointer="/result/period_return",
            primary=True,
        ),
        common.evidence(
            f"history.{inst.ticker}.last_close",
            "{ticker} son kapanışı {end} tarihinde {close} {unit}.",
            disp,
            values={"last_raw_close": result["last_raw_close"]},
            pointer="/result/last_raw_close",
        ),
    ]
    if w.clamped:
        warnings.append(warn(WarningCode.END_CLAMPED_TO_AS_OF, f"end clamped to {as_of}", severity=Severity.INFO))
    return ToolOutput(result, warnings, evidence=ev)


def common_status_insufficient() -> Any:
    from bistharness.core.enums import ToolStatus

    return ToolStatus.INSUFFICIENT_DATA


@tool(
    "get_stock_history",
    version="1.0.0",
    input_model=HistoryInput,
    sources=PRICE_SOURCES,
    description="Point-in-time adjusted OHLCV summary (period return, drawdown, corporate actions, quality flags) "
    "for one BIST stock up to as_of_date; optional rows.",
)
def get_stock_history(ctx: ToolContext, inp: HistoryInput) -> ToolOutput:
    return _history(ctx, inp.ticker, inp.start, inp.end, inp.as_of_date, inp.include_rows, "stock")


@tool(
    "get_index_history",
    version="1.0.0",
    input_model=IndexHistoryInput,
    sources=PRICE_SOURCES,
    description="Point-in-time benchmark index history summary (XU100) up to as_of_date.",
)
def get_index_history(ctx: ToolContext, inp: IndexHistoryInput) -> ToolOutput:
    return _history(ctx, inp.index, inp.start, inp.end, inp.as_of_date, inp.include_rows, "index")


# ----------------------------------------------------------------------------------------------- indicators
class IndicatorsInput(ToolInput):
    ticker: str
    start: date | None = None
    end: date | None = None
    config: dict[str, float | int] = Field(default_factory=dict)
    tail: int = Field(default=0, ge=0, le=250)


def indicator_params(config: dict[str, float | int]) -> indicators.IndicatorParams:
    names = {f.name for f in dataclasses.fields(indicators.IndicatorParams)}
    bad = sorted(set(config) - names)
    if bad:
        raise ToolInputError(f"unknown indicator parameters {bad}; allowed: {sorted(names)}")
    return dataclasses.replace(indicators.IndicatorParams(), **config)  # type: ignore[arg-type]


def _at_end(frame: pd.DataFrame, end: date) -> pd.DataFrame:
    return frame[frame.index <= pd.Timestamp(end)]


@tool(
    "calculate_indicators",
    version="1.0.0",
    input_model=IndicatorsInput,
    sources=PRICE_SOURCES,
    description="SMA/EMA, RSI, MACD, Bollinger (+%b, bandwidth), ATR, KAMA (slope, run), Supertrend (state), "
    "Ichimoku (price vs cloud; no Chikou), volume z-score at the window end, with the market state labels.",
)
def calculate_indicators(ctx: ToolContext, inp: IndicatorsInput) -> ToolOutput:
    inst = common.instrument(ctx, inp.ticker, kind="stock")
    w = common.window(ctx, inp.start, inp.end, inp.as_of_date)
    params = indicator_params(inp.config)
    prices, warnings = common.load_prices(ctx, [inst.ticker], w.as_of)
    ind = _at_end(indicators.compute_indicators(common.ohlcv(prices, inst.ticker), params), w.end)
    if ind.empty:
        return ToolOutput({"ticker": inst.ticker}, warnings, status=common_status_insufficient())
    state = events.market_state(ind)
    last, st = ind.iloc[-1], state.iloc[-1]
    day = ind.index[-1]
    values = {k: (None if pd.isna(v) else v) for k, v in last.items()}
    states = {k: (None if pd.isna(v) else v) for k, v in st.items()}
    if len(ind) < indicators.warmup_bars(params):
        warnings.append(
            warn(
                WarningCode.SHORT_HISTORY, f"{inst.ticker}: {len(ind)} bars < warm-up {indicators.warmup_bars(params)}"
            )
        )
    result: dict[str, Any] = {
        "ticker": inst.ticker,
        "date": day,
        "params": dataclasses.asdict(params),
        "values": values,
        "state": states,
    }
    if inp.tail:
        tail = ind.tail(inp.tail).join(state[["rsi_state", "supertrend_state", "ichimoku_state", "kama_slope_state"]])
        result["tail"] = tail.reset_index()
    disp = {
        "ticker": inst.ticker,
        "date": fmt.tr_date(day),
        "rsi": fmt.num(values["rsi"]) if values["rsi"] is not None else "-",
        "st": {"bullish": "yükseliş", "bearish": "düşüş"}.get(str(states["supertrend_state"]), "tanımsız"),
        "ichi": {
            "above_cloud": "bulutun üstünde",
            "inside_cloud": "bulutun içinde",
            "below_cloud": "bulutun altında",
        }.get(str(states["ichimoku_state"]), "tanımsız"),
        "kama": {"rising": "yükselen", "falling": "düşen", "flat": "yatay"}.get(
            str(states["kama_slope_state"]), "tanımsız"
        ),
        "pctb": fmt.num(values["bb_pctb"]) if values["bb_pctb"] is not None else "-",
        "vz": fmt.num(values["volume_z"]) if values["volume_z"] is not None else "-",
        "period": str(params.rsi_period),
    }
    ev = [
        common.evidence(
            f"indicators.{inst.ticker}.rsi",
            "{ticker} RSI({period}) {date} itibarıyla {rsi}.",
            disp,
            values={"rsi": values["rsi"]},
            pointer="/result/values/rsi",
            primary=True,
        ),
        common.evidence(
            f"indicators.{inst.ticker}.trend_state",
            "{date} itibarıyla {ticker} Supertrend yönü {st}, fiyat Ichimoku {ichi}, KAMA eğimi {kama}.",
            disp,
            values={k: states[k] for k in ("supertrend_state", "ichimoku_state", "kama_slope_state")},
            pointer="/result/state",
            primary=True,
        ),
        common.evidence(
            f"indicators.{inst.ticker}.bollinger_volume",
            "{ticker} Bollinger %b değeri {pctb}, hacim z-skoru {vz} ({date}).",
            disp,
            values={"bb_pctb": values["bb_pctb"], "volume_z": values["volume_z"]},
            pointer="/result/values/bb_pctb",
        ),
    ]
    return ToolOutput(result, warnings, evidence=ev)


# ----------------------------------------------------------------------------------------------- support/resistance
class SupportResistanceInput(ToolInput):
    ticker: str
    start: date | None = None
    end: date | None = None
    tolerance: float = Field(default=0.02, gt=0, le=0.1)
    pivot_k: int = Field(default=5, ge=2, le=20)
    lookback: int = Field(default=250, ge=20, le=1000)
    horizons: list[int] | None = None


@tool(
    "find_support_resistance",
    version="1.0.0",
    input_model=SupportResistanceInput,
    sources=PRICE_SOURCES,
    description="Support/resistance zones from confirmed pivots known at the window end (touches, effective "
    "touches, recency, distance) and the historical bounce statistics of support/resistance touches.",
)
def find_support_resistance(ctx: ToolContext, inp: SupportResistanceInput) -> ToolOutput:
    inst = common.instrument(ctx, inp.ticker, kind="stock")
    w = common.window(ctx, inp.start, inp.end, inp.as_of_date)
    sr = support_resistance.SRParams(pivot_k=inp.pivot_k, tolerance=inp.tolerance, lookback=inp.lookback)
    prices, warnings = common.load_prices(ctx, [inst.ticker], w.as_of)
    full = indicators.compute_indicators(common.ohlcv(prices, inst.ticker))
    upto = _at_end(full, w.end)
    levels = support_resistance.find_support_resistance(upto, sr)
    sp = common.study_params(ctx, inp.horizons or [1, 3, 5, 10])
    eparams = events.EventParams(sr=sr)
    flags = events.detect_events(full, eparams)
    flags = flags[flags.index <= pd.Timestamp(w.end)]
    study = event_study.reversal_event_study(
        full,
        flags,
        events.market_state(full, eparams),
        common.calendar(ctx, w.as_of),
        ticker=inst.ticker,
        start=w.start,
        params=sp,
        event_types=["SUPPORT_TOUCH", "RESISTANCE_TOUCH"],
        main_horizon=sp.horizons[min(2, len(sp.horizons) - 1)],
    )
    warnings += [x for x in study.warnings if x.code != WarningCode.MULTIPLE_TESTING_RISK]
    close = float(upto["close"].iloc[-1])
    result = {
        "ticker": inst.ticker,
        "date": upto.index[-1],
        "last_close": close,
        "params": dataclasses.asdict(sr),
        "levels": levels,
        "touch_statistics": {s.event_type: {"n_events": s.n_events, "horizons": s.horizons} for s in study.studies},
    }
    ev = []
    nearest = {side: next((lv for lv in levels if lv.side == side), None) for side in ("support", "resistance")}
    for side, lv in nearest.items():
        if lv is None:
            continue
        disp = {
            "ticker": inst.ticker,
            "price": fmt.num(lv.price),
            "touches": fmt.integer(lv.touches),
            "strength": fmt.integer(lv.strength),
            "dist": fmt.pct(lv.distance, signed=True),
            "last": fmt.tr_date(lv.last_touch),
            "date": fmt.tr_date(upto.index[-1]),
        }
        word = "destek" if side == "support" else "direnç"
        ev.append(
            common.evidence(
                f"support_resistance.{inst.ticker}.nearest_{side}",
                "{date} itibarıyla en yakın "
                + word
                + " bölgesi {price} TL ({touches} dokunuş, {strength} etkili tepki, "
                "son dokunuş {last}); fiyata uzaklık {dist}.",
                disp,
                values=dataclasses.asdict(lv),
                pointer="/result/levels",
                primary=True,
            )
        )
    for s in study.studies:
        h = next((x for x in s.horizons if x.horizon == study.main_horizon), None)
        if h is None or h.n == 0:
            continue
        word = "destek" if s.event_type == "SUPPORT_TOUCH" else "direnç"
        disp = {
            "ticker": inst.ticker,
            "n": fmt.integer(h.n),
            "k": fmt.integer(h.n_success),
            "h": str(h.horizon),
            "rate": fmt.pct(h.success_rate or 0.0),
            "start": fmt.tr_date(w.start),
            "end": fmt.tr_date(w.end),
        }
        ev.append(
            common.evidence(
                f"support_resistance.{inst.ticker}.{s.event_type.lower()}_stats",
                "{start}–{end} arasında "
                + word
                + " dokunuşlarının {n} tanesinin {k} tanesinde {h} gün sonra beklenen yönde "
                "hareket oldu ({rate}).",
                disp,
                values={"n": h.n, "n_success": h.n_success, "success_rate": h.success_rate, "horizon": h.horizon},
                pointer="/result/touch_statistics",
                kind="statistic",
            )
        )
    excluded = [e for s in study.studies for e in s.excluded]
    return ToolOutput(result, warnings, excluded=excluded, evidence=ev)
