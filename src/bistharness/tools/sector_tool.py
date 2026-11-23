"""rank_sector_relative_strength — Scenario 1 (sector laggard / catch-up)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field

from bistharness.analytics import sector, series
from bistharness.core import formatting as fmt
from bistharness.core.enums import Severity, WarningCode
from bistharness.tools import common
from bistharness.tools.base import ToolContext, ToolInput, ToolInputError, ToolOutput, tool, warn

SECTOR_TR = {
    "Bankacilik": "bankacılık",
    "Sigorta_Araci_Kurum": "sigorta ve aracı kurum",
    "Holding_Yatirim": "holding",
    "Bilisim_Yazilim": "bilişim",
    "Demir_Celik_Boru": "demir çelik",
    "Insaat_Yapi_Malzemeleri": "inşaat ve çimento",
    "GYO": "GYO",
    "Otomotiv_YanSanayi": "otomotiv",
    "Dayanikli_Tuketim": "dayanıklı tüketim",
    "Enerji": "enerji",
    "Petrokimya_Endustri": "petrokimya",
    "Tarim_Gubre": "gübre",
    "Gida_Icecek": "gıda ve içecek",
    "Perakende": "perakende",
    "Havacilik_Lojistik": "havacılık ve lojistik",
    "Savunma_Makine": "savunma",
    "Telekomunikasyon": "telekom",
    "Saglik_Ilac": "sağlık ve ilaç",
    "Madencilik": "madencilik",
}


class SectorInput(ToolInput):
    sector_or_tickers: str | list[str]
    horizon: int = Field(default=20, ge=1, le=250)
    start: date | None = None
    end: date | None = None
    lag_threshold: float = Field(default=-0.05, lt=0)
    windows: list[int] | None = None
    catch_up_horizons: list[int] | None = None


def resolve_group(ctx: ToolContext, spec: str | list[str]) -> tuple[str, list[str]]:
    if isinstance(spec, list):
        tickers = [common.instrument(ctx, t, kind="stock").ticker for t in spec]
        if len(set(tickers)) != len(tickers) or len(tickers) < 2:
            raise ToolInputError("a custom group needs at least two distinct tickers")
        return "/".join(tickers), tickers
    if spec in ctx.universe.peer_groups:
        return spec, list(ctx.universe.peer_groups[spec])
    inst = common.instrument(ctx, spec, kind="stock")
    if inst.peer_group is None:
        raise ToolInputError(f"{spec} has no peer group")
    return inst.peer_group, list(ctx.universe.peer_groups[inst.peer_group])


@tool(
    "rank_sector_relative_strength",
    version="1.0.0",
    input_model=SectorInput,
    sources=("prices",),
    description="Scenario 1: returns of every member of a peer group over several windows, leave-one-out peer "
    "median, lag score, rank, laggards/leaders in strong sectors, persistent laggards, and the historical catch-up "
    "test of laggard entries (hit rate, median catch-up, false positives) over 5/10/20 days.",
)
def rank_sector_relative_strength(ctx: ToolContext, inp: SectorInput) -> ToolOutput:
    group, members = resolve_group(ctx, inp.sector_or_tickers)
    w = common.window(ctx, inp.start, inp.end, inp.as_of_date)
    windows = tuple(sorted(set(inp.windows or [5, 10, 20, 60]) | {inp.horizon}))
    params = sector.SectorParams(
        windows=windows,
        lag_window=inp.horizon,
        lag_threshold=inp.lag_threshold,
        horizons=tuple(sorted(set(inp.catch_up_horizons or [5, 10, 20]))),
        small_group=int(ctx.settings.threshold("small_sector_group")),
    )
    bench = ctx.universe.benchmark
    prices, warnings = common.load_prices(ctx, [bench], w.as_of, optional=members)
    members = common.available(prices, members)
    if len(members) < 2:
        raise ToolInputError(f"{group}: fewer than two members with price data")
    closes = series.column_matrix(prices, members)
    xu = common.ohlcv(prices, bench)["close"]
    snap = sector.sector_snapshot(
        closes, group=group, calendar=common.calendar(ctx, w.end), benchmark=xu, params=params
    )
    study = sector.catch_up_study(
        {group: closes},
        common.calendar(ctx, w.as_of),
        start=w.start,
        end=w.end,
        benchmark=xu,
        params=params,
        study=common.study_params(ctx, params.horizons),
        main_horizon=max(params.horizons),
    )
    warnings += snap.warnings + study.warnings
    for t in snap.persistent_laggards:
        warnings.append(
            warn(
                WarningCode.STRUCTURAL_LAGGARD,
                f"{t}: also lags its peers over {list(params.structural_windows)} days -> structural-laggard candidate",
                severity=Severity.INFO,
                ticker=t,
            )
        )
    h = inp.horizon
    rows_h = [m for m in snap.rows if m.window == h]
    result: dict[str, Any] = {
        "group": group,
        "members": members,
        "members_with_data": snap.members_with_data,
        "date": w.end,
        "horizon": h,
        "lag_threshold": inp.lag_threshold,
        "definitions": {
            "lag_score": "stock return - median return of the OTHER members over the window",
            "strong_sector": "group median return > 0 and > XU100 return over the window",
            "laggard_event": "entry into 'lag_score <= threshold in a strong sector' (one event per episode)",
            "catch_up": "stock forward return - equal-weight basket of the other members > 0",
        },
        "ranking": rows_h,
        "all_windows": snap.rows,
        "group_median": snap.group_median,
        "benchmark_returns": snap.benchmark_returns,
        "strong": snap.strong,
        "laggards": snap.laggards,
        "leaders": snap.leaders,
        "persistent_laggards": snap.persistent_laggards,
        "catch_up": {
            "start": w.start,
            "end": w.end,
            "n_events": study.n_events,
            "horizons": study.horizons,
            "events": study.events,
            "false_positives": study.false_positives,
        },
    }
    ev = []
    n_mem = len(snap.members_with_data)
    group_tr = SECTOR_TR.get(group, group)
    med, br = snap.group_median.get(h), snap.benchmark_returns.get(h)
    if med is not None:
        disp = {
            "group": group_tr,
            "h": str(h),
            "med": fmt.pct(med, signed=True),
            "bench": fmt.pct(br, signed=True) if br is not None else "-",
            "state": "güçlü" if snap.strong.get(h) else "güçlü değil",
            "date": fmt.tr_date(w.end),
        }
        ev.append(
            common.evidence(
                f"sector.{group}.strength.w{h}",
                "{date} itibarıyla {group} grubunun son {h} işlem günü medyan getirisi {med} "
                "(XU100 {bench}); sektör {state}.",
                disp,
                values={"group_median": med, "benchmark": br, "strong": snap.strong.get(h)},
                pointer="/result/group_median",
                primary=True,
            )
        )
    for m in rows_h:
        if m.ret is None or m.lag_score is None:
            continue
        disp = {
            "ticker": m.ticker,
            "h": str(h),
            "ret": fmt.pct(m.ret, signed=True),
            "peer": fmt.pct(m.peer_median, signed=True) if m.peer_median is not None else "-",
            "lag": fmt.pp_from_fraction(m.lag_score),
            "rank": fmt.integer(m.rank or 0),
            "n": fmt.integer(n_mem),
            "pos": common.direction(
                m.lag_score, up="akranlarının önünde", down="akranlarının gerisinde", flat="akranlarıyla aynı"
            ),
        }
        ev.append(
            common.evidence(
                f"sector.{group}.{m.ticker}.lag.w{h}",
                "{ticker} son {h} işlem gününde {ret} getiri sağladı; diğer üyelerin medyanı {peer}, fark {lag} ({pos}); "
                "grup içi sıra {rank}/{n}.",
                disp,
                values={
                    "ret": m.ret,
                    "peer_median": m.peer_median,
                    "lag_score": m.lag_score,
                    "rank": m.rank,
                    "laggard": m.ticker in snap.laggards,
                    "leader": m.ticker in snap.leaders,
                },
                pointer="/result/ranking",
                primary=m.ticker in snap.laggards or m.ticker in snap.leaders,
            )
        )
    for hz in study.horizons:
        if hz.n == 0:
            continue
        disp = {
            "group": group_tr,
            "start": fmt.tr_date(w.start),
            "end": fmt.tr_date(w.end),
            "n": fmt.integer(hz.n),
            "k": fmt.integer(hz.n_catch_up),
            "h": str(hz.horizon),
            "rate": fmt.pct(hz.hit_rate or 0.0),
            "median": fmt.pp_from_fraction(hz.median_relative) if hz.median_relative is not None else "-",
            "fp": fmt.integer(hz.n_false_positive),
            "base": fmt.pct(hz.baseline_hit_rate) if hz.baseline_hit_rate is not None else "-",
        }
        ev.append(
            common.evidence(
                f"sector.{group}.catch_up.h{hz.horizon}",
                "{start}–{end} arasında {group} grubunda {n} geride kalma girişinin {k} tanesinde hisse sonraki {h} günde "
                "akran sepetini geçti ({rate}; geride kalmayan günlerde {base}); medyan kapanma {median}; {fp} yanlış pozitif.",
                disp,
                values={
                    "n": hz.n,
                    "n_catch_up": hz.n_catch_up,
                    "hit_rate": hz.hit_rate,
                    "median_relative": hz.median_relative,
                    "n_false_positive": hz.n_false_positive,
                    "p_rate_vs_baseline": hz.p_rate_vs_baseline,
                    "baseline_hit_rate": hz.baseline_hit_rate,
                },
                pointer="/result/catch_up/horizons",
                kind="statistic",
                primary=True,
            )
        )
    for t in snap.persistent_laggards:
        ev.append(
            common.evidence(
                f"sector.{group}.{t}.persistent_lag",
                "{ticker} yalnız son {h} günde değil, daha uzun pencerelerde de akranlarının gerisinde (yapısal geride "
                "kalma adayı; temel/makro kanıtla ayrıştırılmalı).",
                {"ticker": t, "h": str(h)},
                values={"structural_windows": list(params.structural_windows)},
                pointer="/result/persistent_laggards",
                kind="warning",
                primary=True,
            )
        )
    return ToolOutput(result, warnings, excluded=study.excluded, evidence=ev)
