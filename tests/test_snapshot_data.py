"""Checks against the real frozen snapshot (skipped when data/db/bist.sqlite has not been built yet).

They pin down the data facts found while building the snapshot so a future re-ingest cannot silently regress.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pandas as pd
import pytest

from bistharness.core.config import load_settings, load_universe
from bistharness.core.enums import HARD_BLOCK_CODES
from bistharness.core.pit import PITRepository

DB = load_settings().db_path
pytestmark = [pytest.mark.data, pytest.mark.skipif(not DB.exists(), reason="snapshot DB not built")]
GOLDEN_AS_OF = "2026-09-10"


@pytest.fixture(scope="module")
def repo() -> Iterator[PITRepository]:
    conn = sqlite3.connect(f"{DB.resolve().as_uri()}?mode=ro", uri=True)
    yield PITRepository(conn)
    conn.close()


def test_calendar_excludes_known_closures(repo: PITRepository) -> None:
    cal = repo.trading_calendar(as_of="2026-11-19")
    assert not cal.is_trading_day(pd.Timestamp("2023-02-08").date())  # earthquake closure (yfinance phantom row)
    assert cal.is_trading_day(pd.Timestamp("2024-04-09").date())  # half-day session before bayram
    assert cal.last == pd.Timestamp("2026-11-19").date()  # snapshot keeps completed sessions only


def test_every_universe_ticker_and_benchmark_is_present(repo: PITRepository) -> None:
    u = load_universe()
    tickers = [*u.tickers("course_30"), *u.tickers("tubitak_95"), u.benchmark]
    df = repo.prices(sorted(set(tickers)), "2024-01-01", GOLDEN_AS_OF, as_of=GOLDEN_AS_OF).data
    assert set(df["ticker"]) == set(tickers)
    assert df["date"].max() == pd.Timestamp(GOLDEN_AS_OF)


def test_no_hard_flags_for_course_universe(repo: PITRepository) -> None:
    u = load_universe()
    flags = repo.quality_flags([*u.tickers("course_30"), u.benchmark], as_of="2026-11-19")
    hard = flags[flags["code"].isin([c.value for c in HARD_BLOCK_CODES])]
    assert hard.empty, hard.to_string()


def test_adjusted_returns_stay_inside_price_band(repo: PITRepository) -> None:
    u = load_universe()
    df = repo.prices(list(u.tickers("course_30")), "2023-01-01", "2026-11-19", as_of="2026-11-19").data
    worst = df.groupby("ticker")["close"].apply(lambda s: s.pct_change().abs().max())
    assert (worst < 0.105).all(), worst[worst >= 0.105]


def test_known_vendor_defects_are_repaired(repo: PITRepository) -> None:
    thy = repo.prices("THYAO", "2023-01-05", "2023-01-05", as_of="2023-01-05").data.iloc[0]
    assert thy["raw_close"] == pytest.approx(135.2)  # yfinance truncated bar said 141.8
    akb = repo.prices("AKBNK", "2022-12-16", "2022-12-16", as_of="2022-12-16").data.iloc[0]
    assert akb["raw_volume"] > 250e6  # yfinance said 73M
    # CCOLA 1:11 bonus: ex-date 2024-08-13 (ekofin, price-verified by the price-scraper);
    # yfinance wrongly applies it from 2024-08-01 and has no split record
    acts = repo.corporate_actions("CCOLA", as_of="2026-11-19")
    bonus = acts[acts["kind"] == "split_or_bonus"]
    assert list(bonus["ex_date"]) == ["2024-08-13"]
    assert bonus.iloc[0]["ratio"] == pytest.approx(11.0, rel=1e-3)
    assert bonus.iloc[0]["source"] == "price_scraper"
    ccola = repo.prices("CCOLA", "2024-08-01", "2024-08-01", as_of="2024-08-01").data.iloc[0]
    assert ccola["raw_close"] == pytest.approx(861.0)  # printed price before the ex-date


def test_real_data_is_point_in_time(repo: PITRepository) -> None:
    """Deleting every row after as_of from a copy of the DB must not change any as_of output."""
    tickers = ["THYAO", "ASELS", "TUPRS", "EREGL", "BIMAS", "MGROS", "MAVI", "CCOLA", "XU100"]
    full = repo.prices(tickers, "2024-01-01", GOLDEN_AS_OF, as_of=GOLDEN_AS_OF).data

    mem = sqlite3.connect(":memory:")
    src = sqlite3.connect(f"{DB.resolve().as_uri()}?mode=ro", uri=True)
    src.backup(mem)
    src.close()
    for table, col in [("prices_daily", "date"), ("trading_calendar", "date"), ("corporate_actions", "ex_date")]:
        mem.execute(f"DELETE FROM {table} WHERE {col} > ?", (GOLDEN_AS_OF,))
    mem.commit()
    truncated = PITRepository(mem).prices(tickers, "2024-01-01", GOLDEN_AS_OF, as_of=GOLDEN_AS_OF).data
    mem.close()
    pd.testing.assert_frame_equal(full, truncated)


# ---------------------------------------------------------------------------- fundamentals (KAP XBRL)
@pytest.fixture(scope="module")
def fund_repo(repo: PITRepository) -> PITRepository:
    if repo.meta("fundamentals_coverage_end") is None:
        pytest.skip("fundamentals not ingested")
    return repo


def test_fundamental_knowledge_time_is_the_kap_publish_second(fund_repo: PITRepository) -> None:
    kw = {"metrics": ["revenue"], "durations": ["3M"]}
    thy = fund_repo.fundamentals("THYAO", as_of="2023-05-03", **kw).data
    q1 = thy[thy["fiscal_period"] == "2023Q1"].iloc[0]
    assert q1["value"] == pytest.approx(82_057e6)  # THYAO 2023Q1 revenue, KAP 1146464 (millions TL in the report)
    assert q1["disclosure_datetime"] == "2023-05-03 18:20:57"
    assert "2023Q1" not in set(fund_repo.fundamentals("THYAO", as_of="2023-05-02", **kw).data["fiscal_period"])


def test_tuprs_2026q2_report_is_known_at_the_golden_as_of(fund_repo: PITRepository) -> None:
    reps = fund_repo.fundamental_reports("TUPRS", as_of=GOLDEN_AS_OF, scope="consolidated")
    last = reps.iloc[-1]
    assert (last["report_period"], last["disclosure_datetime"]) == ("2026Q2", "2026-08-04 18:24:32")
    before = fund_repo.fundamental_reports("TUPRS", as_of="2026-08-03", scope="consolidated")
    assert before.iloc[-1]["report_period"] == "2026Q1"


def test_unit_scale_change_is_normalised(fund_repo: PITRepository) -> None:
    """AKBNK reported in thousands TL until 2026Q1 and in millions from 2026Q2; the TRY series must be continuous."""
    df = fund_repo.fundamentals("AKBNK", as_of="2026-09-10", metrics=["total_assets"], scope="consolidated").data
    s = df.set_index("fiscal_period")["value"].sort_index()
    growth = s / s.shift(1)
    assert growth.dropna().between(0.85, 1.35).all(), growth.to_string()
    assert s["2026Q2"] == pytest.approx(4_012_479e6)  # rebuilt BDDK Total column (TL + FX), not the TL column


def test_tms29_detection_matches_config(fund_repo: PITRepository) -> None:
    u = load_universe()
    for ticker in u.all_stock_tickers():
        reps = fund_repo.fundamental_reports(ticker, as_of="2026-11-19")
        recent = reps[reps["period_end"] >= "2024-12-31"]
        if recent.empty:
            continue
        detected = recent["tms29_adjusted"].dropna()
        assert (detected.astype(bool) == u.instrument(ticker).tms29_applies).all(), ticker


# ---------------------------------------------------------------------------- macro + news
def _needs(repo: PITRepository, source: str) -> None:
    if source not in repo.data_version():
        pytest.skip(f"{source} not ingested")


def test_macro_values_and_release_times(repo: PITRepository) -> None:
    _needs(repo, "macro")
    fx = repo.macro("USDTRY", "2024-09-10", "2024-09-10", as_of="2024-09-10").data
    assert fx.iloc[0]["value"] == pytest.approx(33.9904)  # TCMB bulletin 2024/170, ForexBuying
    assert fx.iloc[0]["release_datetime"] == "2024-09-10 15:30:00"
    pol = repo.macro("TCMB_POLICY_RATE", "2025-01-01", GOLDEN_AS_OF, as_of=GOLDEN_AS_OF).data
    assert pol.iloc[-1]["value"] == pytest.approx(37.0)  # effective 2026-01-23; the 36 % of 2026-10-23 is invisible
    cpi = repo.macro("TUFE_YOY", "2026-01-01", GOLDEN_AS_OF, as_of=GOLDEN_AS_OF).data
    last = cpi.iloc[-1]
    assert (last["obs_date"], last["release_datetime"]) == ("2026-08-01", "2026-09-03 10:00:00")


def test_news_is_point_in_time_and_tagged(repo: PITRepository) -> None:
    _needs(repo, "news")
    df = repo.news("2024-01-01", GOLDEN_AS_OF, as_of=GOLDEN_AS_OF, ticker="THYAO").data
    assert len(df) > 20
    assert df["published_at"].max() <= f"{GOLDEN_AS_OF} 23:59:59"
    assert (df["first_published_at"] <= df["published_at"]).all()
    rates = repo.news("2026-01-01", GOLDEN_AS_OF, as_of=GOLDEN_AS_OF, topic="rates").data
    assert len(rates) > 0


def test_cpi_release_rule_matches_tuik_headlines(repo: PITRepository) -> None:
    """Independent check of the TÜİK release rule: the first Bloomberg HT headline with the official number appears
    seconds after 10:00 on the rule date (incl. weekend shifts: 3 Aug 2024 and 3 Oct 2026 were Saturdays)."""
    _needs(repo, "macro")
    _needs(repo, "news")
    cases = {
        "2026-09-01": ("Eylül'de yıllık enflasyon yüzde 29,73", "2026-10-05 10:00:00", 29.73),
        "2025-02-01": ("Şubat'ta yıllık enflasyon yüzde 39,05", "2025-03-03 10:00:00", 39.05),
    }
    for obs_date, (headline, release, value) in cases.items():
        cpi = repo.macro("TUFE_YOY", obs_date, obs_date, as_of="2026-11-19").data.iloc[0]
        assert (cpi["release_datetime"], cpi["value"]) == (release, pytest.approx(value))
        hits = repo.news(release[:10], as_of="2026-11-19").data  # knowledge time may be a later edit
        hit = hits[hits["title"].str.contains(headline, regex=False)]
        assert len(hit) and (hit["first_published_at"] >= release).all(), headline
