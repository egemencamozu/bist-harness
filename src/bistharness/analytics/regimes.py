"""Market regimes known at each day (pure, causal) for regime breakdowns (spec §13, §18).

market_trend(t)  = "rising" if the benchmark's trailing `trend_window`-day return at t is > 0, else "falling".
volatility(t)    = "high" if the benchmark's trailing `vol_window`-day realized volatility at t is above the median
                   of that volatility over all days <= t (expanding, at least `vol_min_history` values), else "low".
Both use only data <= t, so labelling an event day never peeks into the future.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RegimeParams:
    trend_window: int = 20
    vol_window: int = 20
    vol_min_history: int = 60


def market_regimes(benchmark_close: pd.Series, params: RegimeParams | None = None) -> pd.DataFrame:
    p = params or RegimeParams()
    trail = benchmark_close / benchmark_close.shift(p.trend_window) - 1
    trend = pd.Series(np.where(trail > 0, "rising", "falling"), index=benchmark_close.index).where(trail.notna())
    vol = benchmark_close.pct_change().rolling(p.vol_window).std()
    med = vol.expanding(min_periods=p.vol_min_history).median()
    volatility = pd.Series(np.where(vol > med, "high", "low"), index=benchmark_close.index).where(med.notna())
    return pd.DataFrame(
        {"market_trend": trend, "volatility": volatility, "benchmark_trailing_return": trail, "benchmark_vol": vol}
    )
