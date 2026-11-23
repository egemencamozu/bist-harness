"""Technical indicators (pure, causal: the value at t uses only bars <= t).

Defaults equal the instructor's Scenario 3 script (parity-tested in tests/test_indicator_parity.py):
BB(20, 2σ), RSI(14, Wilder EWM), KAMA(10, 2, 30), ATR(10, simple mean of true range), Supertrend(10, 3),
Ichimoku(9, 26, 52), volume MA20. Additions: SMA/EMA, MACD(12, 26, 9), Bollinger %b/bandwidth, volume z-score,
realized volatility.

Deliberate differences from the reference script (documented, tested):
- Supertrend: the reference initialises its final bands on the first bar, where ATR is still NaN; every later
  comparison with NaN is False, so the bands, the Supertrend line and every flip stay NaN/False forever. Here the
  recursion starts on the first bar with a valid ATR and is otherwise identical.
- Ichimoku Chikou span is not computed (it is the close shifted 26 bars into the past = future information when used
  as a feature at t). Senkou A/B are the +26-shifted spans, i.e. built from data 26 bars old.

Input frame: DatetimeIndex, columns open/high/low/close/volume (as_of-anchored adjusted prices from PITRepository).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

OHLCV = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class IndicatorParams:
    bb_window: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    kama_er_period: int = 10
    kama_fast: int = 2
    kama_slow: int = 30
    atr_period: int = 10
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    ichimoku_tenkan: int = 9
    ichimoku_kijun: int = 26
    ichimoku_senkou_b: int = 52
    ichimoku_shift: int = 26
    volume_window: int = 20
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    sma_windows: tuple[int, ...] = (20, 50, 200)
    ema_windows: tuple[int, ...] = (20, 50)
    volatility_window: int = 20


# ----------------------------------------------------------------------------------------------- building blocks
def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window).mean()


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI exactly as the reference: EWM(alpha=1/period, adjust=False); avg_loss == 0 -> NaN."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig}, index=close.index)


def bollinger(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()  # ddof=1 as the reference
    upper, lower = mid + n_std * std, mid - n_std * std
    width = upper - lower
    return pd.DataFrame(
        {
            "bb_mid": mid,
            "bb_upper": upper,
            "bb_lower": lower,
            "bb_pctb": (close - lower) / width.replace(0, np.nan),
            "bb_bandwidth": width / mid,
        },
        index=close.index,
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """max(H-L, |H-C(t-1)|, |L-C(t-1)|); the first bar is H-L (NaNs skipped, as the reference)."""
    prev = close.shift(1)
    return pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10) -> pd.Series:
    """Simple rolling mean of the true range (the reference's definition, not Wilder smoothing)."""
    return true_range(high, low, close).rolling(period).mean()


def kama(close: pd.Series, er_period: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman adaptive moving average, the reference recursion (seeded with the close at bar er_period)."""
    c = close.to_numpy(dtype=float)
    change = (close - close.shift(er_period)).abs()
    volatility = close.diff().abs().rolling(er_period).sum()
    er = change / volatility.replace(0, np.nan)
    fast_sc, slow_sc = 2 / (fast + 1), 2 / (slow + 1)
    sc = ((er * (fast_sc - slow_sc) + slow_sc) ** 2).to_numpy(dtype=float)
    out = np.full(len(c), np.nan)
    if len(c) > er_period:
        out[er_period] = c[er_period]
        for i in range(er_period + 1, len(c)):
            prev = out[i - 1]
            if np.isnan(prev):
                prev = c[i - 1]
            out[i] = prev if np.isnan(sc[i]) else prev + sc[i] * (c[i] - prev)
    return pd.Series(out, index=close.index)


def supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, multiplier: float = 3.0
) -> pd.DataFrame:
    """Supertrend line and direction (+1 bullish, -1 bearish, 0 on the seed bar, NaN before it).

    Same recursion as the reference, started on the first bar with a valid ATR (see module docstring).
    """
    a = atr(high, low, close, period)
    hl2 = (high + low) / 2
    bu = (hl2 + multiplier * a).to_numpy(dtype=float)
    bl = (hl2 - multiplier * a).to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)
    n = len(c)
    fu, fl = np.full(n, np.nan), np.full(n, np.nan)
    line, direction = np.full(n, np.nan), np.full(n, np.nan)
    valid = np.flatnonzero(~np.isnan(bu) & ~np.isnan(bl))
    if len(valid):
        s0 = int(valid[0])
        fu[s0], fl[s0], direction[s0] = bu[s0], bl[s0], 0.0
        for i in range(s0 + 1, n):
            fu[i] = bu[i] if (bu[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
            fl[i] = bl[i] if (bl[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
            prev = line[i - 1]
            if np.isnan(prev):
                line[i], direction[i] = fl[i], 1.0
            elif prev == fu[i - 1]:
                line[i], direction[i] = (fu[i], -1.0) if c[i] <= fu[i] else (fl[i], 1.0)
            else:
                line[i], direction[i] = (fl[i], 1.0) if c[i] >= fl[i] else (fu[i], -1.0)
    return pd.DataFrame({"supertrend": line, "supertrend_dir": direction}, index=close.index)


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
    shift: int = 26,
) -> pd.DataFrame:
    """Tenkan, Kijun and the cloud valid at t (spans computed at t-shift). No Chikou (look-ahead as a feature)."""
    t = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    k = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2
    span_a = ((t + k) / 2).shift(shift)
    span_b = ((high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2).shift(shift)
    spans = pd.concat([span_a, span_b], axis=1)
    return pd.DataFrame(
        {
            "tenkan": t,
            "kijun": k,
            "senkou_a": span_a,
            "senkou_b": span_b,
            # skipna like the reference: while only span A exists, it alone defines the cloud
            "cloud_top": spans.max(axis=1),
            "cloud_bottom": spans.min(axis=1),
        },
        index=high.index,
    )


# ----------------------------------------------------------------------------------------------- full table
def compute_indicators(ohlcv: pd.DataFrame, params: IndicatorParams | None = None) -> pd.DataFrame:
    """All indicators for one instrument; returns the input columns plus one column per indicator."""
    p = params or IndicatorParams()
    missing = [c for c in OHLCV if c not in ohlcv.columns]
    if missing:
        raise ValueError(f"ohlcv frame lacks columns {missing}")
    if not ohlcv.index.is_monotonic_increasing or ohlcv.index.has_duplicates:
        raise ValueError("ohlcv index must be strictly increasing dates")
    df = ohlcv[list(OHLCV)].astype(float).copy()
    c, h, lo, v = df["close"], df["high"], df["low"], df["volume"]

    parts: list[pd.DataFrame | pd.Series] = [df]
    parts += [sma(c, w).rename(f"sma_{w}") for w in p.sma_windows]
    parts += [ema(c, w).rename(f"ema_{w}") for w in p.ema_windows]
    parts.append(rsi(c, p.rsi_period).rename("rsi"))
    parts.append(macd(c, p.macd_fast, p.macd_slow, p.macd_signal))
    parts.append(bollinger(c, p.bb_window, p.bb_std))
    parts.append(atr(h, lo, c, p.atr_period).rename("atr"))
    k = kama(c, p.kama_er_period, p.kama_fast, p.kama_slow)
    parts += [k.rename("kama"), k.diff().rename("kama_slope")]
    parts.append(supertrend(h, lo, c, p.supertrend_period, p.supertrend_multiplier))
    parts.append(ichimoku(h, lo, p.ichimoku_tenkan, p.ichimoku_kijun, p.ichimoku_senkou_b, p.ichimoku_shift))
    vol_ma = v.rolling(p.volume_window).mean()
    vol_sd = v.rolling(p.volume_window).std()
    parts += [
        vol_ma.rename("volume_ma"),
        (v > vol_ma).rename("volume_rise"),
        ((v - vol_ma) / vol_sd.replace(0, np.nan)).rename("volume_z"),
    ]
    ret = c.pct_change()
    parts += [ret.rename("ret_1d"), ret.rolling(p.volatility_window).std().rename("volatility")]
    return pd.concat(parts, axis=1)


def warmup_bars(params: IndicatorParams | None = None) -> int:
    """Bars needed before every indicator is defined (Ichimoku span B: 52 + 26 shift, SMA200, ...)."""
    p = params or IndicatorParams()
    return max(
        p.ichimoku_senkou_b + p.ichimoku_shift,
        max(p.sma_windows, default=0),
        p.macd_slow + p.macd_signal,
        p.bb_window,
        p.kama_er_period + 1,
        p.atr_period + 1,
    )
