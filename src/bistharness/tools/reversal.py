"""detect_reversal_events — Scenario 3 (technical reversal events)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from bistharness.analytics import event_study, events, indicators, regimes
from bistharness.analytics.forward_returns import HorizonStats
from bistharness.core import formatting as fmt
from bistharness.core.enums import Direction
from bistharness.tools import common
from bistharness.tools.base import ToolContext, ToolInput, ToolInputError, ToolOutput, tool

COMBO_RSI_VOLUME = "BB_LOWER_TOUCH+RSI_LOW+VOLUME_RISE"
COMBO_BEARISH = "BB_LOWER_TOUCH+ST_BEARISH+BELOW_CLOUD"
COMBO_DESCRIPTIONS = {
    COMBO_RSI_VOLUME: "alt Bollinger dokunuşu + RSI 40'ın altında + hacim 20 günlük ortalamanın üzerinde",
    COMBO_BEARISH: "alt Bollinger dokunuşu + Supertrend düşüş yönünde + fiyat Ichimoku bulutunun altında",
}
HEADLINE = ("BB_LOWER_TOUCH", "BB_LOWER_REVERSAL", COMBO_RSI_VOLUME, COMBO_BEARISH)
ACTIVE_WINDOW = 5
TR_NAMES = {
    "BB_LOWER_REVERSAL": "alt Bollinger dönüşü",
    "BB_LOWER_TOUCH": "alt Bollinger dokunuşu",
    "BB_MIDDLE_TEST_FROM_ABOVE": "orta banda yukarıdan test",
    "BB_MIDDLE_TEST_FROM_BELOW": "orta banda aşağıdan test",
    "BB_UPPER_TOUCH": "üst Bollinger dokunuşu",
    "BB_UPPER_REVERSAL": "üst Bollinger dönüşü",
    "RSI_LOCAL_TROUGH": "RSI yerel dibi",
    "RSI_TROUGH_VOLUME": "RSI dibi + hacim artışı",
    "RSI_LOCAL_PEAK": "RSI yerel tepesi",
    "RSI_BULLISH_DIVERGENCE": "RSI pozitif uyumsuzluk adayı",
    "RSI_BEARISH_DIVERGENCE": "RSI negatif uyumsuzluk adayı",
    "SUPERTREND_BULLISH_FLIP": "Supertrend yukarı dönüşü",
    "SUPERTREND_BEARISH_FLIP": "Supertrend aşağı dönüşü",
    "KAMA_BULLISH_TURN": "KAMA yukarı dönüşü",
    "KAMA_BEARISH_TURN": "KAMA aşağı dönüşü",
    "ICHIMOKU_BULLISH_BREAKOUT": "Ichimoku bulut üstü kırılımı",
    "ICHIMOKU_BEARISH_BREAKDOWN": "Ichimoku bulut altı kırılımı",
    "ICHIMOKU_CLOUD_REJECTION_FROM_BELOW": "Ichimoku bulut tabanından ret",
    "ICHIMOKU_CLOUD_SUPPORT_FROM_ABOVE": "Ichimoku bulut tavanından destek",
    "ICHIMOKU_ENTER_CLOUD_FROM_ABOVE": "yukarıdan buluta giriş",
    "ICHIMOKU_ENTER_CLOUD_FROM_BELOW": "aşağıdan buluta giriş",
    "SUPPORT_TOUCH": "destek dokunuşu",
    "RESISTANCE_TOUCH": "direnç dokunuşu",
    "TREND_REVERSAL_EVENT": "trend dönüş olayı (Supertrend/Ichimoku/KAMA)",
    "STRONG_REVERSAL_EVENT": "güçlü birleşik dönüş olayı",
    COMBO_RSI_VOLUME: COMBO_DESCRIPTIONS[COMBO_RSI_VOLUME],
    COMBO_BEARISH: COMBO_DESCRIPTIONS[COMBO_BEARISH],
}


class EventConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_types: list[str] | None = None
    horizons: list[int] | None = None
    main_horizon: int = 5
    success_threshold: float = 0.0
    rsi_trough_max: float = 40.0
    combinations: bool = True
    recent: int = Field(default=10, ge=0, le=100)


class ReversalInput(ToolInput):
    ticker: str
    start: date | None = None
    end: date | None = None
    event_config: EventConfig = Field(default_factory=EventConfig)


def _compact(h: HorizonStats | None) -> dict[str, Any] | None:
    if h is None:
        return None
    return {"n": h.n, "n_success": h.n_success, "success_rate": h.success_rate, "mean": h.mean, "median": h.median}


@tool(
    "detect_reversal_events",
    version="1.0.0",
    input_model=ReversalInput,
    sources=("prices",),
    description="Scenario 3: timestamped technical reversal events (Bollinger touches/reversals, RSI troughs/peaks, "
    "Supertrend flips, KAMA turns, Ichimoku breakouts/rejections, support/resistance touches, combined conditions) "
    "with forward-return success rates, reversal strength, regime breakdowns, multiple-testing adjustment and the "
    "explicit list of events whose forward windows are incomplete at as_of.",
)
def detect_reversal_events(ctx: ToolContext, inp: ReversalInput) -> ToolOutput:
    cfg = inp.event_config
    inst = common.instrument(ctx, inp.ticker, kind="stock")
    w = common.window(ctx, inp.start, inp.end, inp.as_of_date)
    sp = common.study_params(ctx, cfg.horizons, cfg.success_threshold)
    if cfg.main_horizon not in sp.horizons:
        raise ToolInputError(f"main_horizon {cfg.main_horizon} must be one of the horizons {sp.horizons}")
    unknown = [t for t in cfg.event_types or [] if t not in events.EVENT_SPECS]
    if unknown:
        raise ToolInputError(f"unknown event types {unknown}; allowed: {sorted(events.EVENT_SPECS)}")
    bench = ctx.universe.benchmark
    prices, warnings = common.load_prices(ctx, [inst.ticker, bench], w.as_of)
    ind = indicators.compute_indicators(common.ohlcv(prices, inst.ticker))
    ep = events.EventParams(rsi_trough_max=cfg.rsi_trough_max)
    flags = events.detect_events(ind, ep)
    flags = flags[flags.index <= pd.Timestamp(w.end)]
    state = events.market_state(ind, ep)
    xu = common.ohlcv(prices, bench)["close"]
    custom: dict[str, tuple[pd.Series, Direction, str]] = {}
    if cfg.combinations:
        touch = flags["BB_LOWER_TOUCH"]
        st = state.reindex(flags.index)
        vol = ind["volume_rise"].reindex(flags.index).fillna(False).astype(bool)
        custom[COMBO_RSI_VOLUME] = (touch & (st["rsi_state"] == "low") & vol, Direction.BULLISH, "combined")
        custom[COMBO_BEARISH] = (
            touch & (st["supertrend_state"] == "bearish") & (st["ichimoku_state"] == "below_cloud"),
            Direction.BULLISH,
            "combined",
        )
    study = event_study.reversal_event_study(
        ind,
        flags,
        state,
        common.calendar(ctx, w.as_of),
        ticker=inst.ticker,
        start=w.start,
        params=sp,
        event_types=cfg.event_types,
        main_horizon=cfg.main_horizon,
        benchmark=xu,
        regimes=regimes.market_regimes(xu),
        custom=custom,
    )
    warnings += study.warnings
    mh = cfg.main_horizon
    summary: list[dict[str, Any]] = []
    horizons: dict[str, Any] = {}
    breakdowns: dict[str, Any] = {}
    for s in study.studies:
        h = next(x for x in s.horizons if x.horizon == mh)
        summary.append(
            {
                "event_type": s.event_type,
                "description_tr": TR_NAMES.get(s.event_type, s.event_type),
                "family": s.family,
                "direction": s.direction,
                "reference_definition": s.event_type in events.REFERENCE_EVENTS,
                "n_events": s.n_events,
                "n": h.n,
                "n_success": h.n_success,
                "success_rate": h.success_rate,
                "success_rate_ci95": h.success_rate_ci95,
                "mean": h.mean,
                "median": h.median,
                "mean_reversal_strength": h.mean_mfe,
                "mean_abnormal_vs_xu100": h.mean_abn_benchmark,
                "baseline_success_rate": h.baseline_success_rate,
                "baseline_mean": h.baseline_mean,
                "p_mean_vs_baseline": h.p_mean_vs_baseline,
                "p_rate_vs_baseline": h.p_rate_vs_baseline,
                "p_bonferroni": s.p_bonferroni,
                "p_bh": s.p_bh,
                "n_independent": h.n_independent,
            }
        )
        horizons[s.event_type] = s.horizons
        breakdowns[s.event_type] = {
            col: {val: _compact(next((x for x in hs if x.horizon == mh), None)) for val, hs in groups.items()}
            for col, groups in s.breakdowns.items()
        }
    recent = study.records.tail(cfg.recent) if cfg.recent and not study.records.empty else pd.DataFrame()
    result: dict[str, Any] = {
        "ticker": inst.ticker,
        "start": w.start,
        "end": w.end,
        "main_horizon": mh,
        "success_definition": f"bullish: forward {mh}-day return > {cfg.success_threshold}; bearish: < -{cfg.success_threshold}",
        "family_size": study.family_size,
        "summary": summary,
        "horizons": horizons,
        "breakdowns_main_horizon": breakdowns,
        "combinations": {k: COMBO_DESCRIPTIONS[k] for k in custom},
        "recent_events": recent,
    }
    ev = []
    for row in summary:
        if row["n"] == 0:
            continue
        name = row["event_type"]
        disp = {
            "ticker": inst.ticker,
            "event": TR_NAMES.get(name, name),
            "start": fmt.tr_date(w.start),
            "end": fmt.tr_date(w.end),
            "n": fmt.integer(row["n"]),
            "k": fmt.integer(row["n_success"]),
            "h": str(mh),
            "rate": fmt.pct(row["success_rate"]),
            "mean": fmt.pct(row["mean"], signed=True),
            "median": fmt.pct(row["median"], signed=True),
            "base": fmt.pct(row["baseline_success_rate"]) if row["baseline_success_rate"] is not None else "-",
            "cmp": common.compare(row["success_rate"], row["baseline_success_rate"]),
        }
        primary = name in HEADLINE or (row["p_bh"] is not None and row["p_bh"] <= 0.10)
        ev.append(
            common.evidence(
                f"reversal.{inst.ticker}.{name}.h{mh}",
                "{start}–{end} arasında {ticker} için {event} {n} kez oluştu; {h} gün sonra {k} tanesi beklenen yönde "
                "sonuçlandı ({rate}; olay dışı günlerdeki {base} oranından {cmp}); ortalama {mean}, medyan {median}.",
                disp,
                values={
                    k: row[k]
                    for k in (
                        "n",
                        "n_success",
                        "success_rate",
                        "mean",
                        "median",
                        "baseline_success_rate",
                        "p_bh",
                        "n_independent",
                    )
                },
                pointer=f"/result/summary/{summary.index(row)}",
                kind="statistic",
                primary=primary,
            )
        )
        if row["p_bh"] is not None:
            ev.append(
                common.evidence(
                    f"reversal.{inst.ticker}.{name}.h{mh}.significance",
                    "{event} için {h} günlük getirinin olay dışı günlerden farkı çoklu test düzeltmesi sonrası "
                    "p={p} (aile büyüklüğü {fam}).",
                    {
                        "event": TR_NAMES.get(name, name),
                        "h": str(mh),
                        "p": fmt.num(row["p_bh"], 3),
                        "fam": fmt.integer(study.family_size),
                    },
                    values={"p_bh": row["p_bh"], "family_size": study.family_size},
                    pointer=f"/result/summary/{summary.index(row)}/p_bh",
                    kind="statistic",
                    primary=name in HEADLINE,
                )
            )
    rows_by = {r["event_type"]: r for r in summary}
    ca, cb = rows_by.get(COMBO_RSI_VOLUME), rows_by.get(COMBO_BEARISH)
    if ca and cb and ca["n"] and cb["n"]:
        ev.append(
            common.evidence(
                f"reversal.{inst.ticker}.combo_comparison",
                "{h} günlük başarı oranı: '{a}' koşulunda {ra} ({na} olay), '{b}' koşulunda {rb} ({nb} olay); ilk "
                "koşulun oranı ikincisinden {cmp}.",
                {
                    "h": str(mh),
                    "a": COMBO_DESCRIPTIONS[COMBO_RSI_VOLUME],
                    "b": COMBO_DESCRIPTIONS[COMBO_BEARISH],
                    "ra": fmt.pct(ca["success_rate"]),
                    "na": fmt.integer(ca["n"]),
                    "rb": fmt.pct(cb["success_rate"]),
                    "nb": fmt.integer(cb["n"]),
                    "cmp": common.compare(ca["success_rate"], cb["success_rate"]),
                },
                values={"n": min(ca["n"], cb["n"]), "rate_a": ca["success_rate"], "rate_b": cb["success_rate"]},
                pointer="/result/summary",
                kind="statistic",
                primary=True,
            )
        )
    # which bullish events fired in the last ACTIVE_WINDOW trading days up to the window end ("is a signal live?")
    recent_days = flags.index[-ACTIVE_WINDOW:]
    active = (
        sorted(
            {
                n
                for n in [
                    *HEADLINE,
                    "RSI_LOCAL_TROUGH",
                    "SUPERTREND_BULLISH_FLIP",
                    "KAMA_BULLISH_TURN",
                    "ICHIMOKU_BULLISH_BREAKOUT",
                    "STRONG_REVERSAL_EVENT",
                ]
                if n in study.records.get("event_type", pd.Series(dtype=str)).values
                and bool(study.records.loc[study.records["event_type"] == n, "event_date"].isin(recent_days).any())
            }
        )
        if not study.records.empty
        else []
    )
    result["active_now"] = {
        "window_trading_days": ACTIVE_WINDOW,
        "from": recent_days[0] if len(recent_days) else None,
        "events": active,
    }
    ev.append(
        common.evidence(
            f"reversal.{inst.ticker}.active_now",
            "{ticker} için {since}–{end} arasındaki son işlem günlerinde oluşan yükseliş yönlü olaylar: {events}.",
            {
                "ticker": inst.ticker,
                "since": fmt.tr_date(recent_days[0]) if len(recent_days) else "-",
                "end": fmt.tr_date(w.end),
                "events": ", ".join(TR_NAMES.get(a, a) for a in active) or "yok",
            },
            values={"active": active, "window_trading_days": ACTIVE_WINDOW},
            pointer="/result/active_now",
            primary=True,
        )
    )
    excluded = [e for s in study.studies for e in s.excluded]
    if excluded:
        last = max(e.event_date for e in excluded)
        ev.append(
            common.evidence(
                f"reversal.{inst.ticker}.excluded_incomplete",
                "{count} olay-ufuk çifti ileri penceresi {asof} itibarıyla tamamlanmadığı için istatistiğe alınmadı "
                "(en son olay {last}).",
                {"count": fmt.integer(len(excluded)), "asof": fmt.tr_date(w.as_of), "last": fmt.tr_date(last)},
                values={"n_excluded": len(excluded)},
                pointer="/excluded_incomplete_events",
                kind="warning",
                primary=True,
            )
        )
    return ToolOutput(result, warnings, excluded=excluded, evidence=ev)
