"""Conservative deterministic verification of explicitly described speech claims."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pandas as pd

from bistharness.analytics.claims import Verdict, compare_observation, forecast_window, quoted_percent_bounds
from bistharness.analytics.fundamentals import growth
from bistharness.tools import common
from bistharness.tools.base import ToolContext

MACRO_METRICS = {
    "tcmb_policy_rate": ("TCMB_POLICY_RATE", "politika faizi"),
    "cpi_yoy": ("TUFE_YOY", "yıllık tüfe"),
    "cpi_mom": ("TUFE_MOM", "aylık tüfe"),
}


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": Verdict.NOT_VERIFIABLE, "reason": reason}


def _annual_revenue(
    ctx: ToolContext, ticker: str, cutoff: datetime, quote: str
) -> tuple[Decimal, dict[str, Any]] | None:
    if ticker not in ctx.universe.instruments or not re.search(r"hasılat|revenue", quote):
        return None
    if not re.search(r"yıllık baz|yıllık hasılat|year.over.year", quote) or re.search(r"çeyrek|quarter", quote):
        return None
    rows = ctx.repo.fundamentals(
        ticker,
        as_of=cutoff.date(),
        knowledge_cutoff=cutoff,
        metrics=["revenue"],
        durations=["12M"],
        scope="consolidated",
        role=None,
        latest_only=False,
    ).data
    current = rows[rows["role"] == "current"]
    years = set(re.findall(r"\b20\d{2}\b", quote))
    if len(years) > 1:
        return None
    if years:
        current = current[current["fiscal_period"].isin([f"{year}Q4" for year in years])]
    current = current[current["fiscal_period"].str.endswith("Q4")]
    if current.empty:
        return None
    latest = current.sort_values(["fiscal_period", "disclosure_datetime", "disclosure_index"]).iloc[-1]
    prior_period = f"{int(latest.fiscal_period[:4]) - 1}Q4"
    pair = rows[
        (rows["disclosure_index"] == latest.disclosure_index)
        & (rows["fiscal_period"].isin([latest.fiscal_period, prior_period]))
    ]
    prior = pair[(pair["role"] == "prior") & (pair["fiscal_period"] == prior_period)]
    if len(prior) != 1 or len(pair) != 2 or prior.iloc[0]["unit"] != latest.unit:
        return None
    current_value, prior_value = Decimal(str(latest.value)), Decimal(str(prior.iloc[0]["value"]))
    if not current_value.is_finite() or not prior_value.is_finite() or prior_value <= 0:
        return None
    return 100 * (current_value / prior_value - 1), {
        "source": "KAP",
        "disclosure_index": int(latest.disclosure_index),
        "disclosed_at": latest.disclosure_datetime,
        "period": latest.fiscal_period,
        "comparison_period": prior_period,
        "metric": "revenue_yoy",
    }


def verify_claim(ctx: ToolContext, claim: dict[str, Any], as_of: date) -> dict[str, Any]:
    cutoff = datetime.fromisoformat(claim["published_at"])
    kind = claim["claim_type"]
    if cutoff.date() > as_of:
        return _unavailable("PUBLICATION_AFTER_AS_OF")
    quote = claim["quote"].strip()
    text = quote.translate(str.maketrans({"İ": "i", "I": "ı"})).lower()
    metric = claim["metric"]
    bounds = quoted_percent_bounds(quote)
    if kind in {"price_move_forecast", "sector_relative_forecast"}:
        if claim["horizon_days"] is None:
            return _unavailable("MISSING_EXPLICIT_HORIZON")
        if kind == "price_move_forecast":
            return _price_forecast(ctx, claim, cutoff, as_of, text)
        return _unavailable("FORECAST_COMPARISON_UNDEFINED")
    if kind == "fundamental_value" and metric == "revenue_growth" and bounds is not None and "azal" not in text:
        obs = _annual_revenue(ctx, claim["subject"], cutoff, text)
        if obs is None:
            return _unavailable("NO_COMPARABLE_ANNUAL_REPORT")
    elif kind == "macro_value" and metric in MACRO_METRICS and bounds is not None:
        code, label = MACRO_METRICS[metric]
        if label not in text or not re.search(r"\b(?:şu anda|bugün|mevcut|currently)\b", text):
            return _unavailable("MACRO_MEASURE_OR_PERIOD_UNCLEAR")
        frame = ctx.repo.macro(code, as_of=cutoff.date(), knowledge_cutoff=cutoff).data
        if frame.empty:
            return _unavailable("NO_MACRO_RELEASE")
        latest = frame.iloc[-1]
        obs = (
            Decimal(str(latest.value)),
            {
                "source": latest.source,
                "source_ref": latest.source_ref,
                "released_at": latest.release_datetime,
                "period": latest.obs_date,
                "metric": code,
            },
        )
    else:
        reason = {
            "opinion": "OPINION",
            "foreign_or_broker_flow": "FLOW_DATA_UNAVAILABLE",
            "volume_flow": "VOLUME_COMPARISON_UNDEFINED",
            "price_move_past": "PRICE_COMPARISON_UNDEFINED",
            "macro_value": "MACRO_MEASURE_OR_PERIOD_UNCLEAR",
        }.get(kind, "FUNDAMENTAL_METRIC_OR_PERIOD_UNCLEAR")
        return _unavailable(reason)
    value, provenance = obs
    assert bounds is not None
    status = compare_observation(value, *bounds)
    if status == Verdict.NOT_VERIFIABLE:
        return _unavailable("MISSING_OBSERVATION")
    return {"status": status, "observed_percent": float(value), "provenance": provenance}


def _price_forecast(
    ctx: ToolContext, claim: dict[str, Any], cutoff: datetime, as_of: date, text: str
) -> dict[str, Any]:
    ticker = claim["subject"]
    direction = claim["direction"]
    horizon = int(claim["horizon_days"])
    if (
        ticker not in ctx.universe.instruments
        or direction not in {"up", "down"}
        or not re.search(rf"\b{horizon}\s+(?:işlem günü|trading days?)\b", text)
        or re.search(r"%|yüzde|percent", text)
        or re.search(r"\b(?:eğer|şayet|if)\b", text)
    ):
        return _unavailable("FORECAST_COMPARISON_UNDEFINED")
    market_close = time.fromisoformat(str(ctx.settings.raw["session"]["close_time"]))
    calendar = common.calendar(ctx, as_of)
    # Use the most recent session whose close was already knowable at publication.
    anchors = [day for day in calendar.days if datetime.combine(day, market_close) <= cutoff]
    if not anchors:
        return _unavailable("MISSING_BASE_SESSION")
    anchor = anchors[-1]
    window = forecast_window(calendar, anchor, as_of, horizon)
    if window.failure is not None or window.end is None:
        return {"status": window.failure, "reason": "MISSING_FORWARD_SESSIONS"}
    prices = ctx.repo.prices(ticker, start=anchor, end=window.end, as_of=window.end).data
    closes = prices.set_index("date")["close"]
    change, _ = growth(closes.get(pd.Timestamp(window.end)), closes.get(pd.Timestamp(anchor)))
    if change is None or not Decimal(str(change)).is_finite():
        return _unavailable("MISSING_PRICE_CLOSE")
    matches = change > 0 if direction == "up" else change < 0
    return {
        "status": Verdict.SUPPORTED if matches else Verdict.CONTRADICTED,
        "observed_percent": 100 * change,
        "provenance": {"source": "prices", "base_session": anchor, "end_session": window.end},
    }
