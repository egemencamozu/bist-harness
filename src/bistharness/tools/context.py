"""Context tools: get_macro_context, get_news_events, get_speech_features.

News and speech are CONTEXT ONLY (CLAUDE.md §11): their evidence candidates never carry numbers taken from
headlines or transcripts in `display`, so an explanation cannot quote an unverified number from them.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd
from pydantic import Field

from bistharness.analytics import macro_stats
from bistharness.core import formatting as fmt
from bistharness.core.enums import Severity, ToolStatus, WarningCode
from bistharness.tools import common
from bistharness.tools.base import ToolContext, ToolInput, ToolInputError, ToolOutput, tool, warn

MACRO_CODES = ("USDTRY", "EURTRY", "TCMB_POLICY_RATE", "FED_TARGET_UPPER", "FED_TARGET_LOWER", "TUFE_YOY", "TUFE_MOM")
# must equal the topic keys of config/news.yaml (tests/test_tools.py checks it)
NEWS_TOPICS = (
    "earnings",
    "dividend",
    "corporate_action",
    "contract",
    "regulation",
    "rates",
    "inflation",
    "fx",
    "fed",
    "commodity",
    "geopolitics",
    "equity_market",
)
SERIES_TR = {
    "USDTRY": "USD/TRY",
    "EURTRY": "EUR/TRY",
    "TCMB_POLICY_RATE": "TCMB politika faizi",
    "TUFE_YOY": "yıllık TÜFE",
    "TUFE_MOM": "aylık TÜFE",
}


class MacroInput(ToolInput):
    start: date | None = None
    end: date | None = None
    ticker_for_corr: str | None = None
    frequency: str = Field(default="W-FRI", pattern="^(D|W-FRI)$")


def _series(df: pd.DataFrame, code: str) -> pd.Series:
    s = df[df["series_code"] == code]
    return pd.Series(s["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(pd.to_datetime(s["obs_date"])))


@tool(
    "get_macro_context",
    version="1.0.0",
    input_model=MacroInput,
    sources=("macro", "prices"),
    description="USD/TRY, EUR/TRY (TCMB 15:30), TCMB policy rate, Fed target range, TÜİK CPI — values released by "
    "the window end with their release times, changes, real policy rate, cumulative CPI over the window, and an "
    "optional stock-FX historical relationship (weekly correlation/beta, USD-based return).",
)
def get_macro_context(ctx: ToolContext, inp: MacroInput) -> ToolOutput:
    w = common.window(ctx, inp.start, inp.end, inp.as_of_date)
    rows = ctx.repo.macro(list(MACRO_CODES), as_of=w.end).data
    snap = macro_stats.macro_snapshot(rows, w.end)
    warnings = list(snap.warnings)
    in_win = rows[(rows["obs_date"] >= w.start.isoformat()) & (rows["obs_date"] <= w.end.isoformat())]
    summary = {}
    for code in MACRO_CODES:
        s = in_win[in_win["series_code"] == code]
        if s.empty:
            continue
        summary[code] = {
            "n_obs": len(s),
            "first": float(s["value"].iloc[0]),
            "last": float(s["value"].iloc[-1]),
            "min": float(s["value"].min()),
            "max": float(s["value"].max()),
        }
    changes = macro_stats.change_points(rows, "TCMB_POLICY_RATE")
    changes = changes[changes["obs_date"] >= pd.Timestamp(w.start)]
    infl = macro_stats.inflation_between(rows, w.start, w.end)
    result: dict[str, Any] = {
        "start": w.start,
        "end": w.end,
        "latest": snap.latest,
        "changes": snap.changes,
        "real_policy_rate": snap.real_policy_rate,
        "fed_mid": snap.fed_mid,
        "window_summary": summary,
        "policy_rate_changes_in_window": changes,
        "inflation_in_window": infl,
        "release_rules": {
            "FX": "TCMB indicative buying rate, bulletin day 15:30",
            "TCMB_POLICY_RATE": "effective day 00:00",
            "FED": "effective day 00:00",
            "TUFE": "3rd of the next month or the next BIST trading day, 10:00",
        },
    }
    ev = []
    lt = snap.latest
    day = fmt.tr_date(w.end)
    if "USDTRY" in lt:
        ch = snap.changes["USDTRY"]
        m1, m12 = ch.get("1m"), ch.get("12m")
        disp = {
            "day": day,
            "v": fmt.num(lt["USDTRY"].value, 4),
            "obs": fmt.tr_date(lt["USDTRY"].obs_date),
            "m1": fmt.pct(m1, signed=True) if m1 is not None else "-",
            "m12": fmt.pct(m12, signed=True) if m12 is not None else "-",
            "l1": "1",
            "l12": "12",
        }
        ev.append(
            common.evidence(
                "macro.USDTRY.latest",
                "TCMB USD/TRY alış kuru {obs} tarihinde {v}; {l1} aylık değişim {m1}, {l12} aylık değişim {m12}.",
                disp,
                values={"value": lt["USDTRY"].value, **ch},
                pointer="/result/latest/USDTRY",
                primary=True,
            )
        )
    if "TCMB_POLICY_RATE" in lt:
        p = lt["TCMB_POLICY_RATE"]
        ch = snap.changes["TCMB_POLICY_RATE"]
        c12 = ch.get("12m")
        disp = {
            "day": day,
            "v": fmt.pct(p.value / 100),
            "since": fmt.tr_date(p.obs_date),
            "c12": fmt.pp(c12) if c12 is not None else "-",
            "l12": "12",
            "real": fmt.pp(snap.real_policy_rate) if snap.real_policy_rate is not None else "-",
        }
        ev.append(
            common.evidence(
                "macro.TCMB_POLICY_RATE.latest",
                "{day} itibarıyla TCMB politika faizi {v} ({since} tarihinden beri geçerli); {l12} ayda {c12} "
                "değişim; yıllık TÜFE'ye göre reel faiz {real}.",
                disp,
                values={"value": p.value, "real_policy_rate": snap.real_policy_rate, **ch},
                pointer="/result/latest/TCMB_POLICY_RATE",
                primary=True,
            )
        )
    if "TUFE_YOY" in lt:
        c = lt["TUFE_YOY"]
        disp = {
            "month": c.obs_date.strftime("%m.%Y"),
            "v": fmt.pct(c.value / 100),
            "rel": fmt.tr_datetime(c.release_datetime),
        }
        ev.append(
            common.evidence(
                "macro.TUFE_YOY.latest",
                "TÜİK yıllık TÜFE {month} döneminde {v} (yayım {rel}).",
                disp,
                values={"value": c.value},
                pointer="/result/latest/TUFE_YOY",
                primary=True,
            )
        )
    if "FED_TARGET_UPPER" in lt and "FED_TARGET_LOWER" in lt:
        disp = {
            "lo": fmt.pct(lt["FED_TARGET_LOWER"].value / 100),
            "hi": fmt.pct(lt["FED_TARGET_UPPER"].value / 100),
            "since": fmt.tr_date(lt["FED_TARGET_UPPER"].obs_date),
        }
        ev.append(
            common.evidence(
                "macro.FED.latest",
                "Fed hedef aralığı {lo}–{hi} ({since} tarihinden beri).",
                disp,
                values={"lower": lt["FED_TARGET_LOWER"].value, "upper": lt["FED_TARGET_UPPER"].value},
                pointer="/result/latest/FED_TARGET_UPPER",
            )
        )
    if infl.cumulative is not None:
        disp = {
            "s": infl.start_month.strftime("%m.%Y"),
            "e": infl.end_month.strftime("%m.%Y"),
            "v": fmt.pct(infl.cumulative),
            "used": fmt.integer(infl.months_used),
            "exp": fmt.integer(infl.months_expected),
        }
        ev.append(
            common.evidence(
                "macro.inflation_window",
                "{s}–{e} arasında açıklanmış {used}/{exp} aylık TÜFE ile birikimli enflasyon {v}.",
                disp,
                values={"cumulative": infl.cumulative, "months_used": infl.months_used},
                pointer="/result/inflation_in_window",
            )
        )
        if not infl.complete:
            warnings.append(
                warn(
                    WarningCode.MISSING_MACRO,
                    f"CPI released for {infl.months_used}/{infl.months_expected} months of the window",
                    severity=Severity.INFO,
                )
            )
    if inp.ticker_for_corr:
        inst = common.instrument(ctx, inp.ticker_for_corr, kind="stock")
        prices, pw = common.load_prices(ctx, [inst.ticker], w.end)
        warnings += pw
        close = common.ohlcv(prices, inst.ticker)["close"]
        rel = {}
        for code in ("USDTRY", "EURTRY"):
            r = macro_stats.fx_relationship(
                close, _series(rows, code), series=code, frequency=inp.frequency, start=w.start
            )
            rel[code] = r
            if r.correlation.pearson is None:
                continue
            freq = "haftalık" if inp.frequency == "W-FRI" else "günlük"
            disp = {
                "ticker": inst.ticker,
                "fx": SERIES_TR[code],
                "freq": freq,
                "n": fmt.integer(r.correlation.n),
                "s": fmt.tr_date(r.start) if r.start else "-",
                "e": fmt.tr_date(r.end) if r.end else "-",
                "r": fmt.num(r.correlation.pearson),
                "p": fmt.num(r.correlation.pearson_p or 1.0, 3),
                "beta": fmt.num(r.beta.beta) if r.beta.beta is not None else "-",
                "sr": fmt.pct(r.stock_return or 0.0, signed=True),
                "fr": fmt.pct(r.fx_return or 0.0, signed=True),
                "usd": fmt.pct(r.stock_return_in_fx or 0.0, signed=True),
                "rdesc": common.correlation_words(r.correlation.pearson),
            }
            ev.append(
                common.evidence(
                    f"macro.{inst.ticker}.{code}.relationship",
                    "{s}–{e} arasında {ticker} ile {fx} {freq} getirileri arasındaki korelasyon {r} ({rdesc}; p={p}, "
                    "{n} gözlem); "
                    "beta {beta}. Aynı dönemde {ticker} TL bazında {sr}, kur {fr}, kur bazında {usd} değişti. Korelasyon "
                    "nedensellik değildir.",
                    disp,
                    values={
                        "pearson": r.correlation.pearson,
                        "p": r.correlation.pearson_p,
                        "n": r.correlation.n,
                        "beta": r.beta.beta,
                        "stock_return_in_fx": r.stock_return_in_fx,
                    },
                    pointer=f"/result/fx_relationship/{code}",
                    kind="statistic",
                    primary=code == "USDTRY",
                )
            )
        result["fx_relationship"] = rel
        result["ticker_for_corr"] = inst.ticker
    return ToolOutput(result, warnings, evidence=ev)


# ----------------------------------------------------------------------------------------------- news
class NewsInput(ToolInput):
    ticker_or_topic: str
    start: date | None = None
    end: date | None = None
    limit: int = Field(default=20, ge=1, le=200)


@tool(
    "get_news_events",
    version="1.0.0",
    input_model=NewsInput,
    sources=("news",),
    description="Timestamped Bloomberg HT news METADATA (title, URL, knowledge time, ticker/topic tags) for a ticker "
    "or a topic up to as_of_date. Contextual evidence only: headline numbers are never evidence.",
)
def get_news_events(ctx: ToolContext, inp: NewsInput) -> ToolOutput:
    w = common.window(ctx, inp.start, inp.end, inp.as_of_date)
    key = inp.ticker_or_topic.strip()
    if key.lower() in NEWS_TOPICS:
        ticker, topic = None, key.lower()
    else:
        ticker, topic = common.instrument(ctx, key, kind="stock").ticker, None
    pf = ctx.repo.news(w.start, w.end, as_of=w.as_of, ticker=ticker, topic=topic)
    df = pf.data
    warnings = list(pf.warnings)
    topics: dict[str, int] = {}
    for t in df["topics"]:
        for x in json.loads(t or "[]"):
            topics[x] = topics.get(x, 0) + 1
    items = df.sort_values("published_at", ascending=False).head(inp.limit)
    items = items.assign(
        tickers=items["tickers"].map(lambda s: json.loads(s or "[]")),
        topics=items["topics"].map(lambda s: json.loads(s or "[]")),
    )
    if len(df) < 3:
        warnings.append(warn(WarningCode.SPARSE_NEWS, f"{key}: {len(df)} news item(s) in the window"))
    result = {
        "query": {"ticker": ticker, "topic": topic},
        "start": w.start,
        "end": w.end,
        "count": len(df),
        "by_topic": dict(sorted(topics.items())),
        "by_event_type": df["event_type"].fillna("none").value_counts().sort_index().to_dict(),
        "items": items[["published_at", "first_published_at", "title", "url", "tickers", "topics", "event_type"]],
        "note": "metadata only; published_at = conservative knowledge time (latest edit); headlines are context, "
        "not verified facts",
    }
    disp = {
        "key": ticker or topic or key,
        "n": fmt.integer(len(df)),
        "s": fmt.tr_date(w.start),
        "e": fmt.tr_date(w.end),
    }
    ev = [
        common.evidence(
            f"news.{disp['key']}.count",
            "{s}–{e} arasında '{key}' ile etiketli {n} haber (Bloomberg HT metadata) var; haberler bağlamsal "
            "kanıttır, içerdikleri sayılar doğrulanmış veri değildir.",
            disp,
            values={"count": len(df)},
            pointer="/result/count",
            kind="fact",
            primary=True,
        )
    ]
    if len(df):
        last = items.iloc[0]
        ev.append(
            common.evidence(
                f"news.{disp['key']}.latest",
                "En son ilgili haber {d} tarihli (başlık sonuçta; başlıktaki ifadeler doğrulanmadan kanıt "
                "olarak kullanılmaz).",
                {"d": fmt.tr_datetime(str(last["published_at"]))},
                values={"title": last["title"], "url": last["url"]},
                pointer="/result/items/0",
                kind="fact",
            )
        )
    return ToolOutput(result, warnings, evidence=ev)


# ----------------------------------------------------------------------------------------------- speech
class SpeechInput(ToolInput):
    source_id_or_topic: str


@tool(
    "get_speech_features",
    version="1.0.0",
    input_model=SpeechInput,
    sources=("speech",),
    description="Timestamped transcript segments of selected public finance videos (URL, channel, segment range, "
    "topics, stance, quality) published up to as_of_date. Expert opinion is context, not ground truth.",
)
def get_speech_features(ctx: ToolContext, inp: SpeechInput) -> ToolOutput:
    key = inp.source_id_or_topic.strip()
    if not key:
        raise ToolInputError("source_id_or_topic is required")
    by_source = ctx.repo.speech_segments(as_of=inp.as_of_date, source_id=key).data
    df = by_source if not by_source.empty else ctx.repo.speech_segments(as_of=inp.as_of_date, topic=key).data
    if df.empty:
        w = warn(WarningCode.SPEECH_NOT_AVAILABLE, f"no transcribed segment for {key!r} published by {inp.as_of_date}")
        return ToolOutput({"query": key, "segments": []}, [w], status=ToolStatus.INSUFFICIENT_DATA)
    warnings = []
    low = df[df["quality"].fillna(0) < 0.6]
    if len(low):
        warnings.append(
            warn(WarningCode.LOW_TRANSCRIPT_QUALITY, f"{len(low)} segment(s) with transcript quality < 0.6")
        )
    segs = df.assign(topics=df["topics"].map(lambda s: json.loads(s or "[]")))
    ev = [
        common.evidence(
            f"speech.{r.source_id}.{int(r.segment_start)}",
            "{ch} kanalının {d} tarihli videosunda ({rng}) konu: {topics}; görüş: {stance}. Uzman görüşü "
            "bağlamdır, doğrulanmış veri değildir.",
            {
                "ch": str(r.channel or "-"),
                "d": fmt.tr_date(str(r.published_at)),
                "rng": f"{int(r.segment_start) // 60}:{int(r.segment_start) % 60:02d}–"
                f"{int(r.segment_end) // 60}:{int(r.segment_end) % 60:02d}",
                "topics": ", ".join(r.topics) or "-",
                "stance": str(r.stance or "-"),
            },
            values={"url": r.url, "quality": r.quality},
            pointer="/result/segments",
            kind="fact",
        )
        for r in segs.itertuples()
    ]
    return ToolOutput({"query": key, "segments": segs.drop(columns=["text"])}, warnings, evidence=ev)
