"""test_weekday_pattern — Scenario 2 (weekday and multi-day patterns)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field

from bistharness.analytics import weekday
from bistharness.analytics.forward_returns import StudyParams
from bistharness.core import formatting as fmt
from bistharness.core.calendar import TradingCalendar
from bistharness.tools import common
from bistharness.tools.base import ToolContext, ToolInput, ToolInputError, ToolOutput, tool

DAY_TR = {"Mon": "Pzt", "Tue": "Sal", "Wed": "Çar", "Thu": "Per", "Fri": "Cum"}
WEEKDAY_PRESETS: dict[str, weekday.WeekdayPattern] = {
    "MON_TUE_WED_DOWN__THU_FRI": weekday.WeekdayPattern(
        (("Mon", -1), ("Tue", -1), ("Wed", -1)), ("Thu", "Fri"), descriptive_outcome_signs=(("Thu", 1), ("Fri", 1))
    ),
    "MON_DOWN__FRI": weekday.WeekdayPattern((("Mon", -1),), ("Fri",)),
    "MON_TO_THU_UP__FRI": weekday.WeekdayPattern((("Mon", 1), ("Tue", 1), ("Wed", 1), ("Thu", 1)), ("Fri",)),
}
SEQUENCE_PRESETS: dict[str, weekday.SequencePattern] = {
    "THREE_DOWN_DAYS": weekday.SequencePattern("consecutive_down", 3),
    "LARGE_DOWN_DAY": weekday.SequencePattern("large_down", threshold=0.03),
}


class WeekdayInput(ToolInput):
    ticker: str
    pattern: str | dict[str, Any] = "MON_TUE_WED_DOWN__THU_FRI"
    in_sample_start: date | None = None
    in_sample_end: date | None = None
    out_of_sample_start: date | None = None
    out_of_sample_end: date | None = None
    tx_cost_bps: float = Field(default=10.0, ge=0, le=500)
    market_sign: int | None = None


def parse_pattern(
    spec: str | dict[str, Any], market_sign: int | None
) -> weekday.WeekdayPattern | weekday.SequencePattern:
    if isinstance(spec, str):
        if spec in WEEKDAY_PRESETS:
            p = WEEKDAY_PRESETS[spec]
            return weekday.WeekdayPattern(p.condition, p.outcome, spec, p.descriptive_outcome_signs, market_sign)
        if spec in SEQUENCE_PRESETS:
            return SEQUENCE_PRESETS[spec]
        raise ToolInputError(f"unknown pattern {spec!r}; presets: {sorted(WEEKDAY_PRESETS) + sorted(SEQUENCE_PRESETS)}")
    try:
        if "sequence" in spec:
            return weekday.SequencePattern(
                str(spec["sequence"]), int(spec.get("length", 3)), float(spec.get("threshold", 0.03))
            )
        cond = tuple((str(d), int(s)) for d, s in dict(spec["condition"]).items())
        return weekday.WeekdayPattern(cond, tuple(spec["outcome"]), str(spec.get("name", "")), (), market_sign)
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolInputError(f"invalid pattern {spec!r}: {exc}") from exc


def _label_tr(p: weekday.WeekdayPattern) -> str:
    cond = ", ".join(f"{DAY_TR[d]} {'yükseliş' if s > 0 else 'düşüş'}" for d, s in p.condition)
    return f"[{cond}] → {'-'.join(DAY_TR[d] for d in p.outcome)} getirisi"


@tool(
    "test_weekday_pattern",
    version="1.0.0",
    input_model=WeekdayInput,
    sources=("prices",),
    description="Scenario 2: a weekday condition (e.g. Mon<0, Tue<0, Wed<0) and a LATER outcome (e.g. compounded "
    "Thu-Fri return), or a multi-day sequence (3 down days, large down day): occurrences, conditional vs "
    "unconditional mean/median/positive rate, after transaction costs, in-sample vs out-of-sample (by date), "
    "Welch/binomial/permutation tests, sign-family Bonferroni/BH adjustment and stability flags.",
)
def test_weekday_pattern(ctx: ToolContext, inp: WeekdayInput) -> ToolOutput:
    inst = common.instrument(ctx, inp.ticker, kind="stock")
    as_of = inp.as_of_date
    is_start = inp.in_sample_start or ctx.settings.date("analysis_start")
    is_end = inp.in_sample_end or date(2025, 12, 31)
    oos_start = inp.out_of_sample_start or date(2026, 1, 1)
    oos_end = min(inp.out_of_sample_end or as_of, as_of)
    if not (is_start <= is_end < oos_start <= oos_end):
        raise ToolInputError(
            "periods must satisfy in_sample_start <= in_sample_end < out_of_sample_start <= out_of_sample_end"
        )
    if is_end > as_of:
        raise ToolInputError("in-sample period ends after as_of_date")
    pattern = parse_pattern(inp.pattern, inp.market_sign)
    cost = inp.tx_cost_bps / 10_000
    bench = ctx.universe.benchmark
    prices, warnings = common.load_prices(ctx, [inst.ticker, bench], as_of)
    close = common.ohlcv(prices, inst.ticker)["close"]
    periods = {"in_sample": (is_start, is_end), "out_of_sample": (oos_start, oos_end)}
    if isinstance(pattern, weekday.SequencePattern):
        return _sequence(ctx, inst.ticker, close, pattern, periods, as_of, warnings)
    ret = weekday.daily_returns(close)
    bret = weekday.daily_returns(common.ohlcv(prices, bench)["close"]) if pattern.market_sign is not None else None
    res = weekday.evaluate_weekday_pattern(
        ret,
        pattern,
        periods=periods,
        as_of=as_of,
        cost=cost,
        benchmark_returns=bret,
        study=common.study_params(ctx),
        seed=ctx.settings.seed,
    )
    stats_by_period = {
        k: weekday.weekday_statistics(ret[(ret.index >= common.ts(s)) & (ret.index <= common.ts(e))])
        for k, (s, e) in periods.items()
    }
    effect = {
        k: weekday.weekday_effect_test(ret[(ret.index >= common.ts(s)) & (ret.index <= common.ts(e))])
        for k, (s, e) in periods.items()
    }
    is_r, oos_r = res.periods
    is_eff, oos_eff = is_r.mean_difference, oos_r.mean_difference
    small = int(ctx.settings.threshold("small_sample"))
    stability = {
        "in_sample_effect": is_eff,
        "out_of_sample_effect": oos_eff,
        "same_sign_out_of_sample": None if is_eff is None or oos_eff is None else (is_eff > 0) == (oos_eff > 0),
        "out_of_sample_sufficient": oos_r.condition_weeks >= small,
        "in_sample_significant_after_adjustment": is_r.p_bh is not None and is_r.p_bh < 0.05,
        "net_of_cost_positive_in_sample": is_r.conditional.mean_after_cost is not None
        and is_r.conditional.mean_after_cost > 0,
    }
    for r in res.periods:
        warnings += r.warnings
    result: dict[str, Any] = {
        "ticker": inst.ticker,
        "pattern": {
            "label": pattern.label,
            "label_tr": _label_tr(pattern),
            "condition": pattern.condition,
            "outcome": pattern.outcome,
            "market_sign": pattern.market_sign,
        },
        "condition_vs_outcome": "the outcome days come after every condition day (no outcome inside the condition)",
        "tx_cost_bps": inp.tx_cost_bps,
        "periods": {r.period: r for r in res.periods},
        "weekday_statistics": stats_by_period,
        "weekday_effect_tests": effect,
        "stability": stability,
    }
    ev = []
    label = _label_tr(pattern)
    for r in res.periods:
        if r.complete_weeks == 0:
            continue
        name = "örneklem içi" if r.period == "in_sample" else "örneklem dışı"
        c, u = r.conditional, r.unconditional
        disp = {
            "ticker": inst.ticker,
            "label": label,
            "name": name,
            "start": fmt.tr_date(r.start),
            "end": fmt.tr_date(r.end),
            "weeks": fmt.integer(r.complete_weeks),
            "k": fmt.integer(r.condition_weeks),
            "mean": fmt.pct(c.mean, signed=True) if c.mean is not None else "-",
            "median": fmt.pct(c.median, signed=True) if c.median is not None else "-",
            "pos": fmt.pct(c.positive_rate) if c.positive_rate is not None else "-",
            "uncond": fmt.pct(u.mean, signed=True) if u.mean is not None else "-",
            "net": fmt.pct(c.mean_after_cost, signed=True) if c.mean_after_cost is not None else "-",
            "bps": fmt.num(inp.tx_cost_bps, 0),
            "p": fmt.num(r.p_bh, 3) if r.p_bh is not None else "-",
            "fam": fmt.integer(r.family_size),
        }
        ev.append(
            common.evidence(
                f"weekday.{inst.ticker}.{r.period}",
                "{ticker} {label}: {name} ({start}–{end}) {weeks} tam haftanın {k} tanesinde koşul oluştu; bu haftalarda "
                "sonuç ortalaması {mean}, medyanı {median}, pozitif oranı {pos} (tüm haftalarda ortalama {uncond}); {bps} "
                "baz puan maliyet sonrası {net}; {fam} örüntülük ailede düzeltilmiş p={p}.",
                disp,
                values={
                    "n": r.condition_weeks,
                    "complete_weeks": r.complete_weeks,
                    "mean": c.mean,
                    "unconditional_mean": u.mean,
                    "mean_after_cost": c.mean_after_cost,
                    "p_bh": r.p_bh,
                },
                pointer=f"/result/periods/{r.period}",
                kind="statistic",
                primary=True,
            )
        )
        if r.full_sequence_count is not None:
            ev.append(
                common.evidence(
                    f"weekday.{inst.ticker}.{r.period}.full_sequence",
                    "{name} dönemde tam haftalık dizi (koşul + sonuç günleri beklenen yönde) {cnt} kez görüldü "
                    "(tam haftaların {freq}'i); bu betimsel bir sıklıktır, test değildir.",
                    {
                        "name": name,
                        "cnt": fmt.integer(r.full_sequence_count),
                        "freq": fmt.pct(r.full_sequence_frequency or 0.0),
                    },
                    values={"full_sequence_count": r.full_sequence_count},
                    pointer=f"/result/periods/{r.period}",
                    kind="fact",
                )
            )
    if stability["same_sign_out_of_sample"] is not None:
        ev.append(
            common.evidence(
                f"weekday.{inst.ticker}.stability",
                "Koşullu-koşulsuz fark örneklem içinde {is_eff}, örneklem dışında {oos_eff}; işaret {same}; örneklem dışı "
                "koşul sayısı {n} ({suff}).",
                {
                    "is_eff": fmt.pp_from_fraction(is_eff or 0.0),
                    "oos_eff": fmt.pp_from_fraction(oos_eff or 0.0),
                    "same": "aynı" if stability["same_sign_out_of_sample"] else "ters",
                    "n": fmt.integer(oos_r.condition_weeks),
                    "suff": "yeterli" if stability["out_of_sample_sufficient"] else "yetersiz örneklem",
                },
                values=stability,
                pointer="/result/stability",
                kind="statistic",
                primary=True,
            )
        )
    return ToolOutput(result, warnings, excluded=res.excluded, evidence=ev)


def _sequence(
    ctx: ToolContext,
    ticker: str,
    close: Any,
    pattern: weekday.SequencePattern,
    periods: dict[str, tuple[date, date]],
    as_of: date,
    warnings: list[Any],
) -> ToolOutput:
    cal: TradingCalendar = common.calendar(ctx, as_of)
    sp: StudyParams = common.study_params(ctx, [1, 2, 3, 5])
    out: dict[str, Any] = {}
    excluded = []
    ev = []
    for name, (s, e) in periods.items():
        t = weekday.evaluate_sequence_pattern(close, pattern, cal, start=s, end=e, study=sp)
        out[name] = t
        excluded += t.excluded
        warnings += t.warnings
        h = next(x for x in t.horizons if x.horizon == 1)
        if h.n:
            disp = {
                "ticker": ticker,
                "label": pattern.label_tr,
                "name": "örneklem içi" if name == "in_sample" else "örneklem dışı",
                "n": fmt.integer(h.n),
                "rate": fmt.pct(h.success_rate or 0.0),
                "mean": fmt.pct(h.mean or 0.0, signed=True),
                "base": fmt.pct(h.baseline_mean, signed=True) if h.baseline_mean is not None else "-",
            }
            ev.append(
                common.evidence(
                    f"weekday.{ticker}.{name}.sequence",
                    "{ticker} '{label}' koşulu {name} dönemde {n} kez oluştu; ertesi gün beklenen yönde (tepki) oranı {rate}, "
                    "ortalama ertesi gün getirisi {mean} (tüm günlerde {base}).",
                    disp,
                    values={"n": h.n, "success_rate": h.success_rate, "mean": h.mean},
                    pointer=f"/result/periods/{name}",
                    kind="statistic",
                    primary=True,
                )
            )
    result = {"ticker": ticker, "pattern": {"label": pattern.label, "kind": pattern.kind}, "periods": out}
    return ToolOutput(result, warnings, excluded=excluded, evidence=ev)


test_weekday_pattern.__test__ = False  # type: ignore[attr-defined]  # a tool, not a pytest test
