"""Support/resistance from confirmed pivots (pure, point-in-time).

Pivot: bar p is a pivot high if high(p) is strictly above the k previous highs and >= the k next highs (pivot low
mirrored). It needs k future bars, so it is CONFIRMED at bar p+k and only exists for analyses at t >= p+k.
Level: pivots (highs and lows together, role reversal allowed) confirmed in the last `lookback` bars are clustered by
price: sorted ascending, a pivot joins the current cluster while (price - cluster_min) / cluster_min <= tolerance.
A cluster with >= min_touches pivots is a level; zone = [min, max] of its pivot prices, price = median.
Relative to the last close a level is support (zone_high < close) or resistance (zone_low > close); a zone that
contains the close is reported as `at_price`.
Pivot reversal strength (known at confirmation): low pivot close(p+k)/low(p) - 1, high pivot 1 - close(p+k)/high(p).
`strength` = number of pivots in the level whose reversal strength >= tolerance ("effective touches").

Touch events (for the reversal-event study): on bar t, with the levels known at t-1, a support touch is
close(t-1) > zone_high, low(t) <= zone_high*(1+tol), close(t) >= zone_low*(1-tol); resistance mirrored.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SRParams:
    pivot_k: int = 5
    tolerance: float = 0.02
    lookback: int = 250
    min_touches: int = 2
    max_levels: int = 5  # per side in the snapshot


@dataclass(frozen=True)
class Pivot:
    pos: int  # bar of the extreme
    confirmed_pos: int  # pos + k
    date: pd.Timestamp
    confirmed_date: pd.Timestamp
    kind: str  # "high" | "low"
    price: float
    reversal_strength: float
    volume_z: float | None


@dataclass(frozen=True)
class Level:
    side: str  # "support" | "resistance" | "at_price"
    price: float
    zone_low: float
    zone_high: float
    touches: int
    strength: int
    first_touch: pd.Timestamp
    last_touch: pd.Timestamp
    known_from: pd.Timestamp  # confirmation date of the min_touches-th pivot
    bars_since_last_touch: int
    distance: float  # (price - close) / close at the snapshot bar
    mean_reversal_strength: float
    mean_volume_z: float | None


def find_pivots(df: pd.DataFrame, k: int = 5) -> list[Pivot]:
    """df: DatetimeIndex, high/low/close (+ optional volume_z). Pivots ordered by confirmation bar."""
    h = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    vz = df["volume_z"].to_numpy(dtype=float) if "volume_z" in df.columns else None
    idx = df.index
    out: list[Pivot] = []
    for p in range(k, len(df) - k):
        q = p + k
        if np.isnan(h[p]) or np.isnan(lo[p]):
            continue
        z = None if vz is None or np.isnan(vz[p]) else float(vz[p])
        if h[p] > np.nanmax(h[p - k : p]) and h[p] >= np.nanmax(h[p + 1 : q + 1]):
            out.append(Pivot(p, q, idx[p], idx[q], "high", float(h[p]), float(1 - c[q] / h[p]), z))
        if lo[p] < np.nanmin(lo[p - k : p]) and lo[p] <= np.nanmin(lo[p + 1 : q + 1]):
            out.append(Pivot(p, q, idx[p], idx[q], "low", float(lo[p]), float(c[q] / lo[p] - 1), z))
    out.sort(key=lambda pv: (pv.confirmed_pos, pv.pos, pv.kind))
    return out


def _cluster(pivots: list[Pivot], tolerance: float) -> list[list[Pivot]]:
    clusters: list[list[Pivot]] = []
    for pv in sorted(pivots, key=lambda x: (x.price, x.pos)):
        if clusters and (pv.price - clusters[-1][0].price) / clusters[-1][0].price <= tolerance:
            clusters[-1].append(pv)
        else:
            clusters.append([pv])
    return clusters


def levels_at(pivots: list[Pivot], t: int, close_t: float, index: pd.DatetimeIndex, params: SRParams) -> list[Level]:
    """Levels known at bar t (pivots confirmed in (t - lookback, t]), nearest first within each side."""
    known = [pv for pv in pivots if t - params.lookback < pv.confirmed_pos <= t]
    levels: list[Level] = []
    for cl in _cluster(known, params.tolerance):
        if len(cl) < params.min_touches:
            continue
        prices = np.array([pv.price for pv in cl])
        lo, hi = float(prices.min()), float(prices.max())
        side = "support" if hi < close_t else "resistance" if lo > close_t else "at_price"
        by_conf = sorted(cl, key=lambda pv: pv.confirmed_pos)
        vz = [pv.volume_z for pv in cl if pv.volume_z is not None]
        last = max(cl, key=lambda pv: pv.pos)
        levels.append(
            Level(
                side=side,
                price=float(np.median(prices)),
                zone_low=lo,
                zone_high=hi,
                touches=len(cl),
                strength=sum(pv.reversal_strength >= params.tolerance for pv in cl),
                first_touch=min(cl, key=lambda pv: pv.pos).date,
                last_touch=last.date,
                known_from=by_conf[params.min_touches - 1].confirmed_date,
                bars_since_last_touch=t - last.pos,
                distance=float(np.median(prices)) / close_t - 1,
                mean_reversal_strength=float(np.mean([pv.reversal_strength for pv in cl])),
                mean_volume_z=float(np.mean(vz)) if vz else None,
            )
        )
    levels.sort(key=lambda lv: (abs(lv.distance), lv.price))
    return levels


def find_support_resistance(df: pd.DataFrame, params: SRParams | None = None) -> list[Level]:
    """Snapshot at the last bar of df (= as_of): up to max_levels supports and resistances plus at-price zones."""
    p = params or SRParams()
    if df.empty:
        return []
    pivots = find_pivots(df, p.pivot_k)
    t = len(df) - 1
    levels = levels_at(pivots, t, float(df["close"].iloc[-1]), df.index, p)
    supports = [lv for lv in levels if lv.side == "support"][: p.max_levels]
    resistances = [lv for lv in levels if lv.side == "resistance"][: p.max_levels]
    at_price = [lv for lv in levels if lv.side == "at_price"]
    return at_price + supports + resistances


def touch_events(df: pd.DataFrame, params: SRParams | None = None) -> pd.DataFrame:
    """Daily support/resistance touch flags using only levels known on the previous bar.

    Returns columns support_touch, resistance_touch (bool) and support_level, resistance_level (level price).
    """
    p = params or SRParams()
    n = len(df)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    pivots = find_pivots(df, p.pivot_k)
    sup = np.zeros(n, dtype=bool)
    res = np.zeros(n, dtype=bool)
    sup_lv = np.full(n, np.nan)
    res_lv = np.full(n, np.nan)
    tol = p.tolerance
    first_conf = pivots[0].confirmed_pos if pivots else n
    for t in range(max(1, first_conf + 1), n):
        if np.isnan(c[t - 1]) or np.isnan(c[t]):
            continue
        for lv in levels_at(pivots, t - 1, c[t - 1], df.index, p):
            reaches_support = c[t - 1] > lv.zone_high and lo[t] <= lv.zone_high * (1 + tol)
            if not sup[t] and reaches_support and c[t] >= lv.zone_low * (1 - tol):
                sup[t], sup_lv[t] = True, lv.price
            reaches_resistance = c[t - 1] < lv.zone_low and hi[t] >= lv.zone_low * (1 - tol)
            if not res[t] and reaches_resistance and c[t] <= lv.zone_high * (1 + tol):
                res[t], res_lv[t] = True, lv.price
    return pd.DataFrame(
        {"support_touch": sup, "resistance_touch": res, "support_level": sup_lv, "resistance_level": res_lv},
        index=df.index,
    )
