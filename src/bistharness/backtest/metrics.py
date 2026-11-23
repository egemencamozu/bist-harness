"""Performance metrics from daily returns and trades (pure).

- cumulative return = prod(1 + r) - 1 (nominal); real = (1 + nominal) / (1 + CPI change over the same months) - 1
- annualised return / volatility with 252 trading days
- Sharpe(rf=0) = mean(r) / std(r) * sqrt(252); Sharpe(policy) uses the daily risk-free rate derived from the TCMB
  policy rate KNOWN on each day: rf_d = (1 + rate_d / 100) ** (1 / 252) - 1. With idle cash earning 0 a low-exposure
  strategy has a very negative Sharpe(policy); run_backtest therefore also reports the same trades with idle cash
  earning rf_d ("cash_at_policy_rate").
- max drawdown on the compounded equity curve (negative number)
- win rate over CLOSED trades only (open trades are reported separately)
- benchmark difference = strategy cumulative - benchmark cumulative (fraction points)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bistharness.backtest.engine import Trade

TRADING_DAYS = 252


@dataclass(frozen=True)
class ReturnMetrics:
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    n_days: int
    cumulative: float | None
    annualized: float | None
    volatility: float | None
    sharpe_rf0: float | None
    sharpe_policy: float | None
    max_drawdown: float | None


def _f(x: float) -> float | None:
    return None if x is None or not math.isfinite(x) else float(x)


def max_drawdown(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    equity = (1 + returns.fillna(0.0)).cumprod()
    peak = equity.cummax().clip(lower=1.0)  # the curve starts at 1.0 before the first return
    return _f(float((equity / peak - 1).min()))


def daily_risk_free(policy_rate: pd.Series, days: pd.DatetimeIndex) -> pd.Series:
    """Step series of annual policy rates (%, index = effective day) -> daily rate on each trading day."""
    if policy_rate.empty:
        return pd.Series(np.nan, index=days)
    r = policy_rate.sort_index().reindex(days.union(policy_rate.index)).ffill().reindex(days)
    return (1 + r / 100) ** (1 / TRADING_DAYS) - 1


def return_metrics(returns: pd.Series, rf_daily: pd.Series | None = None) -> ReturnMetrics:
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return ReturnMetrics(None, None, 0, None, None, None, None, None, None)
    cum = float(np.prod(1 + r.to_numpy()) - 1)
    ann = (1 + cum) ** (TRADING_DAYS / n) - 1 if cum > -1 else -1.0
    sd = float(r.std(ddof=1)) if n > 1 else float("nan")
    sharpe0 = float(r.mean()) / sd * math.sqrt(TRADING_DAYS) if n > 1 and sd > 0 else float("nan")
    sharpe_p = float("nan")
    if rf_daily is not None:
        ex = (r - rf_daily.reindex(r.index)).dropna()
        sdx = float(ex.std(ddof=1)) if len(ex) > 1 else float("nan")
        if len(ex) > 1 and sdx > 0:
            sharpe_p = float(ex.mean()) / sdx * math.sqrt(TRADING_DAYS)
    return ReturnMetrics(
        start=r.index[0],
        end=r.index[-1],
        n_days=n,
        cumulative=_f(cum),
        annualized=_f(ann),
        volatility=_f(sd * math.sqrt(TRADING_DAYS)) if n > 1 else None,
        sharpe_rf0=_f(sharpe0),
        sharpe_policy=_f(sharpe_p),
        max_drawdown=max_drawdown(r),
    )


@dataclass(frozen=True)
class TradeStats:
    n_signals: int  # executed trades (closed + open)
    n_closed: int
    n_open: int
    win_rate: float | None  # closed trades with net return > 0
    mean_net: float | None
    median_net: float | None
    best: float | None
    worst: float | None
    mean_holding_days: float | None


def trade_stats(trades: Sequence[Trade]) -> TradeStats:
    closed = [t for t in trades if t.status == "closed"]
    x = np.array([t.net_return for t in closed], dtype=float)
    return TradeStats(
        n_signals=len(trades),
        n_closed=len(closed),
        n_open=len(trades) - len(closed),
        win_rate=_f(float((x > 0).mean())) if len(x) else None,
        mean_net=_f(float(x.mean())) if len(x) else None,
        median_net=_f(float(np.median(x))) if len(x) else None,
        best=_f(float(x.max())) if len(x) else None,
        worst=_f(float(x.min())) if len(x) else None,
        mean_holding_days=_f(float(np.mean([t.holding_days for t in closed]))) if closed else None,
    )


def real_return(nominal: float | None, inflation: float | None) -> float | None:
    if nominal is None or inflation is None:
        return None
    return _f((1 + nominal) / (1 + inflation) - 1)
