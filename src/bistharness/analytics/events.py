"""Technical reversal events (Scenario 3) and the market state recorded with each event (pure, causal).

Event date = CONFIRMATION date (CLAUDE.md §2): e.g. an RSI local trough formed at t-1 is only known at t, so the
event is dated t. Every rule below uses bars <= t only (tested by prefix invariance in tests/test_events.py).

The eight reference events (instructor Scenario 3) keep their exact definitions:
BB_LOWER_REVERSAL, RSI_LOCAL_TROUGH (< 40), RSI_TROUGH_VOLUME, KAMA_BULLISH_TURN, SUPERTREND_BULLISH_FLIP,
ICHIMOKU_BULLISH_BREAKOUT, TREND_REVERSAL_EVENT (= Supertrend flip | Ichimoku breakout | KAMA turn) and
STRONG_REVERSAL_EVENT (= BB lower reversal & RSI trough & volume rise & trend reversal).
The remaining families complete the specification's mandatory list (§8): band touches and middle-band tests,
upper-band reversal, RSI peaks and divergence candidates, bearish flips/turns, KAMA-price crosses, Ichimoku
breakdown/rejection/return into the cloud, and support/resistance touches.

KAMA-price crosses are NOT a separate event: KAMA(t) - KAMA(t-1) = sc(t) * (C(t) - KAMA(t-1)) and
C(t) - KAMA(t) = (1 - sc(t)) * (C(t) - KAMA(t-1)) with 0 < sc < 1, so "close above KAMA" and "KAMA slope > 0" have
the same sign on every bar and the cross IS the slope turn (proven in tests/test_events.py). Counting both would
duplicate events and inflate the multiple-testing family. Adaptive trend persistence is recorded as the state
`kama_run` (signed number of consecutive bars with the current slope sign).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from bistharness.analytics.support_resistance import SRParams, touch_events
from bistharness.core.enums import Direction

BULL, BEAR = Direction.BULLISH, Direction.BEARISH


@dataclass(frozen=True)
class EventSpec:
    name: str
    family: str
    direction: Direction
    reference: bool  # defined exactly as in the instructor's Scenario 3 script
    description_tr: str


_SPECS = [
    EventSpec(
        "BB_LOWER_REVERSAL",
        "bollinger",
        BULL,
        True,
        "Dün alt banda eşit veya altında kapanış, bugün alt bandın üzerinde kapanış",
    ),
    EventSpec("BB_LOWER_TOUCH", "bollinger", BULL, False, "Gün içi düşük alt Bollinger bandına değdi"),
    EventSpec(
        "BB_MIDDLE_TEST_FROM_ABOVE",
        "bollinger",
        BULL,
        False,
        "Orta bandın üzerinden gelen fiyat orta banda değdi (devam = yukarı)",
    ),
    EventSpec(
        "BB_MIDDLE_TEST_FROM_BELOW",
        "bollinger",
        BEAR,
        False,
        "Orta bandın altından gelen fiyat orta banda değdi (ret = aşağı)",
    ),
    EventSpec("BB_UPPER_TOUCH", "bollinger", BEAR, False, "Gün içi yüksek üst Bollinger bandına değdi"),
    EventSpec(
        "BB_UPPER_REVERSAL",
        "bollinger",
        BEAR,
        False,
        "Dün üst banda eşit veya üzerinde kapanış, bugün üst bandın altında kapanış",
    ),
    EventSpec("RSI_LOCAL_TROUGH", "rsi", BULL, True, "RSI dünkü değerde yerel dip yaptı ve dip < 40 (bugün teyit)"),
    EventSpec("RSI_TROUGH_VOLUME", "rsi", BULL, True, "RSI yerel dibi + hacim 20 günlük ortalamanın üzerinde"),
    EventSpec("RSI_LOCAL_PEAK", "rsi", BEAR, False, "RSI dünkü değerde yerel tepe yaptı ve tepe > 60 (bugün teyit)"),
    EventSpec(
        "RSI_BULLISH_DIVERGENCE",
        "rsi",
        BULL,
        False,
        "Fiyat daha düşük dip, RSI daha yüksek dip (pozitif uyumsuzluk adayı)",
    ),
    EventSpec(
        "RSI_BEARISH_DIVERGENCE",
        "rsi",
        BEAR,
        False,
        "Fiyat daha yüksek tepe, RSI daha düşük tepe (negatif uyumsuzluk adayı)",
    ),
    EventSpec("SUPERTREND_BULLISH_FLIP", "supertrend", BULL, True, "Supertrend yönü düşüşten yükselişe döndü"),
    EventSpec("SUPERTREND_BEARISH_FLIP", "supertrend", BEAR, False, "Supertrend yönü yükselişten düşüşe döndü"),
    EventSpec("KAMA_BULLISH_TURN", "kama", BULL, True, "KAMA eğimi sıfır/negatiften pozitife döndü"),
    EventSpec("KAMA_BEARISH_TURN", "kama", BEAR, False, "KAMA eğimi sıfır/pozitiften negatife döndü"),
    EventSpec("ICHIMOKU_BULLISH_BREAKOUT", "ichimoku", BULL, True, "Kapanış bulutun üst sınırını yukarı kırdı"),
    EventSpec("ICHIMOKU_BEARISH_BREAKDOWN", "ichimoku", BEAR, False, "Kapanış bulutun alt sınırını aşağı kırdı"),
    EventSpec(
        "ICHIMOKU_CLOUD_REJECTION_FROM_BELOW",
        "ichimoku",
        BEAR,
        False,
        "Bulutun altındaki fiyat bulut tabanına değip altında kapandı",
    ),
    EventSpec(
        "ICHIMOKU_CLOUD_SUPPORT_FROM_ABOVE",
        "ichimoku",
        BULL,
        False,
        "Bulutun üstündeki fiyat bulut tavanına değip üstünde kapandı",
    ),
    EventSpec("ICHIMOKU_ENTER_CLOUD_FROM_ABOVE", "ichimoku", BEAR, False, "Kapanış yukarıdan bulutun içine girdi"),
    EventSpec("ICHIMOKU_ENTER_CLOUD_FROM_BELOW", "ichimoku", BULL, False, "Kapanış aşağıdan bulutun içine girdi"),
    EventSpec(
        "SUPPORT_TOUCH",
        "support_resistance",
        BULL,
        False,
        "Fiyat bilinen bir destek bölgesine değdi ve bölgenin altında kapanmadı",
    ),
    EventSpec(
        "RESISTANCE_TOUCH",
        "support_resistance",
        BEAR,
        False,
        "Fiyat bilinen bir direnç bölgesine değdi ve bölgenin üstünde kapanmadı",
    ),
    EventSpec(
        "TREND_REVERSAL_EVENT",
        "combined",
        BULL,
        True,
        "Supertrend yukarı dönüşü VEYA Ichimoku yukarı kırılımı VEYA KAMA yukarı dönüşü",
    ),
    EventSpec(
        "STRONG_REVERSAL_EVENT", "combined", BULL, True, "Alt bant dönüşü VE RSI dibi VE hacim artışı VE trend dönüşü"
    ),
]
EVENT_SPECS: dict[str, EventSpec] = {s.name: s for s in _SPECS}
REFERENCE_EVENTS: tuple[str, ...] = tuple(s.name for s in _SPECS if s.reference)


@dataclass(frozen=True)
class EventParams:
    rsi_trough_max: float = 40.0  # reference
    rsi_peak_min: float = 60.0  # mirror of the reference trough rule
    divergence_lookback: int = 60  # bars back to the previous RSI extreme
    divergence_rsi_max: float = 50.0  # bullish divergence troughs below this (bearish peaks above 100 - this)
    kama_flat_tolerance: float = 0.0005  # |KAMA slope| / KAMA below this -> "flat"
    volume_high_z: float = 1.0
    volume_low_z: float = -1.0
    sr: SRParams = field(default_factory=SRParams)


def _shape_extrema(r: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(trough, peak) confirmed at t for an extreme at t-1 (the reference's 3-bar shape rule)."""
    trough = (r.shift(1) < r.shift(2)) & (r.shift(1) < r)
    peak = (r.shift(1) > r.shift(2)) & (r.shift(1) > r)
    return trough, peak


def _divergence(ind: pd.DataFrame, extreme: pd.Series, *, bullish: bool, params: EventParams) -> pd.Series:
    """At a confirmed RSI extreme (formed at t-1) compare with the previous one within the lookback."""
    rsi = ind["rsi"].to_numpy(dtype=float)
    close = ind["close"].to_numpy(dtype=float)
    out = np.zeros(len(ind), dtype=bool)
    prev: int | None = None
    for t in (int(x) for x in np.flatnonzero(extreme.to_numpy(dtype=bool))):
        e = t - 1  # bar of the extreme
        in_zone = rsi[e] < params.divergence_rsi_max if bullish else rsi[e] > 100 - params.divergence_rsi_max
        if not in_zone:
            continue
        if prev is not None and e - prev <= params.divergence_lookback:
            if bullish:
                out[t] = close[e] < close[prev] and rsi[e] > rsi[prev]
            else:
                out[t] = close[e] > close[prev] and rsi[e] < rsi[prev]
        prev = e
    return pd.Series(out, index=ind.index)


def detect_events(ind: pd.DataFrame, params: EventParams | None = None) -> pd.DataFrame:
    """Boolean event flags (one column per EVENT_SPECS entry) from compute_indicators() output."""
    p = params or EventParams()
    c, hi, lo = ind["close"], ind["high"], ind["low"]
    prev_c = c.shift(1)
    bl, bm, bu = ind["bb_lower"], ind["bb_mid"], ind["bb_upper"]
    top, bottom = ind["cloud_top"], ind["cloud_bottom"]
    slope = ind["kama_slope"]
    st_dir = ind["supertrend_dir"]
    rsi = ind["rsi"]
    trough, peak = _shape_extrema(rsi)

    ev: dict[str, pd.Series] = {}
    ev["BB_LOWER_REVERSAL"] = (prev_c <= bl.shift(1)) & (c > bl)
    ev["BB_LOWER_TOUCH"] = lo <= bl
    ev["BB_MIDDLE_TEST_FROM_ABOVE"] = (prev_c > bm.shift(1)) & (lo <= bm)
    ev["BB_MIDDLE_TEST_FROM_BELOW"] = (prev_c < bm.shift(1)) & (hi >= bm)
    ev["BB_UPPER_TOUCH"] = hi >= bu
    ev["BB_UPPER_REVERSAL"] = (prev_c >= bu.shift(1)) & (c < bu)
    ev["RSI_LOCAL_TROUGH"] = trough & (rsi.shift(1) < p.rsi_trough_max)
    ev["RSI_TROUGH_VOLUME"] = ev["RSI_LOCAL_TROUGH"] & ind["volume_rise"].astype(bool)
    ev["RSI_LOCAL_PEAK"] = peak & (rsi.shift(1) > p.rsi_peak_min)
    ev["RSI_BULLISH_DIVERGENCE"] = _divergence(ind, trough, bullish=True, params=p)
    ev["RSI_BEARISH_DIVERGENCE"] = _divergence(ind, peak, bullish=False, params=p)
    ev["SUPERTREND_BULLISH_FLIP"] = (st_dir.shift(1) == -1) & (st_dir == 1)
    ev["SUPERTREND_BEARISH_FLIP"] = (st_dir.shift(1) == 1) & (st_dir == -1)
    ev["KAMA_BULLISH_TURN"] = (slope.shift(1) <= 0) & (slope > 0)
    ev["KAMA_BEARISH_TURN"] = (slope.shift(1) >= 0) & (slope < 0)
    ev["ICHIMOKU_BULLISH_BREAKOUT"] = (prev_c <= top.shift(1)) & (c > top)
    ev["ICHIMOKU_BEARISH_BREAKDOWN"] = (prev_c >= bottom.shift(1)) & (c < bottom)
    ev["ICHIMOKU_CLOUD_REJECTION_FROM_BELOW"] = (prev_c < bottom.shift(1)) & (hi >= bottom) & (c < bottom)
    ev["ICHIMOKU_CLOUD_SUPPORT_FROM_ABOVE"] = (prev_c > top.shift(1)) & (lo <= top) & (c > top)
    inside = (c >= bottom) & (c <= top)
    ev["ICHIMOKU_ENTER_CLOUD_FROM_ABOVE"] = (prev_c > top.shift(1)) & inside
    ev["ICHIMOKU_ENTER_CLOUD_FROM_BELOW"] = (prev_c < bottom.shift(1)) & inside
    touches = touch_events(ind, p.sr)
    ev["SUPPORT_TOUCH"] = touches["support_touch"]
    ev["RESISTANCE_TOUCH"] = touches["resistance_touch"]
    ev["TREND_REVERSAL_EVENT"] = (
        ev["SUPERTREND_BULLISH_FLIP"] | ev["ICHIMOKU_BULLISH_BREAKOUT"] | ev["KAMA_BULLISH_TURN"]
    )
    ev["STRONG_REVERSAL_EVENT"] = (
        ev["BB_LOWER_REVERSAL"] & ev["RSI_LOCAL_TROUGH"] & ind["volume_rise"].astype(bool) & ev["TREND_REVERSAL_EVENT"]
    )
    out = pd.DataFrame({k: ev[k].fillna(False).astype(bool) for k in EVENT_SPECS}, index=ind.index)
    return out


def kama_run(slope: pd.Series) -> pd.Series:
    """Signed run length of the KAMA slope sign: +3 = third consecutive rising bar, -2 = second falling bar."""
    sign = np.sign(slope.to_numpy(dtype=float))
    out = np.full(len(sign), np.nan)
    run = 0.0
    for i, sg in enumerate(sign):
        if np.isnan(sg):
            run = 0.0
            continue
        run = run + sg if sg != 0 and np.sign(run) == sg else sg
        out[i] = run
    return pd.Series(out, index=slope.index)


def market_state(ind: pd.DataFrame, params: EventParams | None = None) -> pd.DataFrame:
    """Categorical state at each bar, recorded with every event (spec §8 example record)."""
    p = params or EventParams()
    c = ind["close"]
    rsi = ind["rsi"]
    rsi_state = pd.Series(
        np.select([rsi < p.rsi_trough_max, rsi > p.rsi_peak_min], ["low", "high"], "neutral"), index=ind.index
    ).where(rsi.notna())
    st = ind["supertrend_dir"]
    st_state = pd.Series(np.select([st == 1, st == -1], ["bullish", "bearish"], "undefined"), index=ind.index)
    rel_slope = ind["kama_slope"] / ind["kama"]
    kama_state = pd.Series(
        np.select(
            [rel_slope > p.kama_flat_tolerance, rel_slope < -p.kama_flat_tolerance], ["rising", "falling"], "flat"
        ),
        index=ind.index,
    ).where(rel_slope.notna())
    top, bottom = ind["cloud_top"], ind["cloud_bottom"]
    ichi = pd.Series(np.select([c > top, c < bottom], ["above_cloud", "below_cloud"], "inside_cloud"), index=ind.index)
    ichi = ichi.where(top.notna())
    vz = ind["volume_z"]
    vol = pd.Series(
        np.select([vz > p.volume_high_z, vz < p.volume_low_z], ["high", "low"], "normal"), index=ind.index
    ).where(vz.notna())
    return pd.DataFrame(
        {
            "close": c,
            "rsi": rsi,
            "rsi_state": rsi_state,
            "supertrend_state": st_state.where(st.notna()),
            "kama_slope_state": kama_state,
            "ichimoku_state": ichi,
            "volume_regime": vol,
            "bb_pctb": ind["bb_pctb"],
            "price_vs_kama": c / ind["kama"] - 1,
            "kama_run": kama_run(ind["kama_slope"]),
        },
        index=ind.index,
    )


def event_records(flags: pd.DataFrame, state: pd.DataFrame, *, ticker: str) -> pd.DataFrame:
    """Long table: one row per (event_type, event_date) with direction, family and the state at the event."""
    rows = []
    for name in flags.columns:
        dates = flags.index[flags[name].to_numpy(dtype=bool)]
        if len(dates) == 0:
            continue
        spec = EVENT_SPECS[name]
        part = state.loc[dates].copy()
        part.insert(0, "event_date", dates)
        part.insert(0, "event_type", name)
        part.insert(0, "ticker", ticker)
        part["direction"] = spec.direction.value
        part["family"] = spec.family
        rows.append(part.reset_index(drop=True))
    cols = ["ticker", "event_type", "event_date", *state.columns, "direction", "family"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return (
        pd.concat(rows, ignore_index=True)[cols]
        .sort_values(["event_date", "event_type"], kind="stable")
        .reset_index(drop=True)
    )
