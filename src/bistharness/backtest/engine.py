"""Event-driven long-only backtest engine (pure, point-in-time).

Timing (CLAUDE.md §6, spec §18 "signal shifting"): a signal is decided with information known at the close of day t
(knowledge time <= t 23:59:59) and executed at the OPEN of t+1. A trade is held `holding_days` trading days and
closed at the open of entry_day + holding_days (exit_mode="open"). One position per ticker; signals while a
position is open are ignored (counted as `skipped_signals`). Costs: tx_cost_bps + slippage_bps per side,
net = open_exit*(1-c) / (open_entry*(1+c)) - 1.
A trade whose exit day is after as_of is OPEN: it is marked to the last close <= as_of, shown separately and never
counted in the win rate. A signal on the last calendar day (no t+1 known) is reported as pending.

Portfolio: N equal sleeves (one per ticker in the universe), each sleeve is either invested in its open trade or in
cash earning 0; the portfolio's daily return is the mean of the sleeve returns (daily rebalanced to 1/N).
Daily sleeve returns: entry day close/(open*(1+c)) - 1, holding days close/prev_close - 1, exit day
open*(1-c)/prev_close - 1 — so compounding the sleeve's daily returns reproduces each trade's net return exactly.
Prices are the as_of-anchored adjusted series (dividends and splits do not create fake returns).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CostModel:
    tx_cost_bps: float = 10.0
    slippage_bps: float = 0.0

    @property
    def per_side(self) -> float:
        return (self.tx_cost_bps + self.slippage_bps) / 10_000


@dataclass(frozen=True)
class Trade:
    ticker: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp | None  # None while open
    exit_price: float  # exit open, or last close for an open trade
    gross_return: float
    net_return: float
    holding_days: int  # trading days held (to as_of for an open trade)
    status: str  # "closed" | "open"


@dataclass
class SimulationResult:
    trades: list[Trade]
    sleeve_returns: pd.DataFrame  # calendar day x ticker
    portfolio_returns: pd.Series
    exposure: pd.Series  # share of sleeves invested at each day's close
    skipped_signals: int
    pending_signals: list[tuple[str, pd.Timestamp]] = field(default_factory=list)


def simulate(
    signals: Mapping[str, Sequence[pd.Timestamp]],
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    days: pd.DatetimeIndex,
    *,
    holding_days: int,
    costs: CostModel,
    universe: Sequence[str],
) -> SimulationResult:
    """signals: ticker -> signal dates (decided at that close). opens/closes: adjusted, date x ticker."""
    if holding_days < 1:
        raise ValueError("holding_days must be >= 1")
    c = costs.per_side
    n = len(days)
    pos = {d: i for i, d in enumerate(days)}
    o = opens.reindex(index=days, columns=list(universe)).to_numpy(dtype=float)
    cl = closes.reindex(index=days, columns=list(universe)).to_numpy(dtype=float)
    sleeves = np.zeros((n, len(universe)))
    invested = np.zeros((n, len(universe)), dtype=bool)
    trades: list[Trade] = []
    skipped = 0
    pending: list[tuple[str, pd.Timestamp]] = []
    for j, tk in enumerate(universe):
        busy_until = -1  # last bar index occupied by the current trade (its exit day)
        for sd in sorted({pd.Timestamp(x) for x in signals.get(tk, ())}):
            i = pos.get(sd)
            if i is None:
                raise ValueError(f"{tk}: signal {sd.date()} is not a calendar day")
            e = i + 1
            if e >= n:
                pending.append((tk, sd))
                continue
            if e <= busy_until:
                skipped += 1
                continue
            if np.isnan(o[e, j]) or o[e, j] <= 0:
                skipped += 1  # no executable open (halt): the signal is not tradable
                continue
            x = e + holding_days  # exit at this day's open
            entry_px = o[e, j]
            if x < n and not np.isnan(o[x, j]):
                exit_px, status, last = o[x, j], "closed", x
            else:
                last = min(x, n - 1) if x < n else n - 1
                # open at as_of (or exit open missing): mark to the last available close
                while last > e and np.isnan(cl[last, j]):
                    last -= 1
                exit_px, status = cl[last, j], "open"
            gross = exit_px / entry_px - 1
            if status == "closed":
                net = exit_px * (1 - c) / (entry_px * (1 + c)) - 1
            else:
                net = exit_px / (entry_px * (1 + c)) - 1  # no exit cost charged yet
            trades.append(
                Trade(
                    tk,
                    sd,
                    days[e],
                    float(entry_px),
                    days[x] if status == "closed" else None,
                    float(exit_px),
                    float(gross),
                    float(net),
                    (x if status == "closed" else last) - e,
                    status,
                )
            )
            # daily sleeve returns
            prev = entry_px * (1 + c)
            end_hold = x - 1 if status == "closed" else last
            for k in range(e, end_hold + 1):
                px = cl[k, j]
                if np.isnan(px):
                    continue  # missing bar: return carried into the next valid bar
                sleeves[k, j] = px / prev - 1
                invested[k, j] = True
                prev = px
            if status == "closed":
                sleeves[x, j] = exit_px * (1 - c) / prev - 1
            busy_until = x if status == "closed" else n
    sleeve_df = pd.DataFrame(sleeves, index=days, columns=list(universe))
    port = sleeve_df.mean(axis=1) if len(universe) else pd.Series(0.0, index=days)
    exposure = pd.Series(invested.mean(axis=1) if len(universe) else 0.0, index=days)
    return SimulationResult(trades, sleeve_df, port, exposure, skipped, pending)


def buy_and_hold_returns(closes: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    """Equal-weight (daily rebalanced) close-to-close returns of the given instruments; first day 0."""
    cl = closes.reindex(days)
    r = cl.pct_change(fill_method=None)
    out = r.mean(axis=1, skipna=True).fillna(0.0)
    out.iloc[0] = 0.0
    return out
