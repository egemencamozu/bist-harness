from __future__ import annotations

import copy

import pytest

from bistharness.core.config import load_settings, load_universe, universe_from_dict
from bistharness.core.enums import FundamentalTemplate
from bistharness.core.errors import ConfigError


def test_course_universe_has_30_unique_tickers() -> None:
    u = load_universe()
    course = u.tickers("course_30")
    assert len(course) == 30
    assert len(set(course)) == 30
    assert u.active == "course_30"


def test_tubitak_universe_has_95_tickers_and_excludes_course_only_tralt() -> None:
    u = load_universe()
    t95 = u.tickers("tubitak_95")
    assert len(t95) == 95
    assert "TRALT" not in t95
    # 29 of the 30 course tickers are inside the TÜBİTAK map
    assert len(set(u.tickers("course_30")) & set(t95)) == 29


def test_peer_groups_and_templates() -> None:
    u = load_universe()
    assert u.instrument("AKBNK").peer_group == "Bankacilik"
    assert len(u.peers("AKBNK")) == 8
    assert u.instrument("AKBNK").template is FundamentalTemplate.BANK
    assert u.instrument("AKBNK").tms29_applies is False
    assert u.instrument("ISMEN").template is FundamentalTemplate.BROKERAGE  # ticker override beats group default
    assert u.instrument("TUPRS").template is FundamentalTemplate.INDUSTRIAL
    assert u.peers("TRALT") == ("TRALT",)
    assert u.instrument("XU100").kind == "index"
    assert u.instrument("BIMAS").course_sector == "Retail Trade"


def test_duplicate_peer_membership_is_rejected() -> None:
    raw = {
        "active_universe": "u",
        "benchmark": "XU100",
        "benchmarks": {"XU100": {"yahoo": "XU100.IS"}},
        "peer_groups": {"A": ["X", "Y"], "B": ["Y"]},
        "universes": {"u": {"tickers": ["X"]}},
    }
    with pytest.raises(ConfigError):
        universe_from_dict(raw)


def test_unknown_ticker_in_universe_is_rejected() -> None:
    raw = {
        "active_universe": "u",
        "benchmark": "XU100",
        "benchmarks": {"XU100": {"yahoo": "XU100.IS"}},
        "peer_groups": {"A": ["X"]},
        "universes": {"u": {"tickers": ["X", "NOPE"]}},
    }
    with pytest.raises(ConfigError):
        universe_from_dict(copy.deepcopy(raw))


def test_settings_paths_are_project_relative() -> None:
    s = load_settings()
    assert s.db_path.is_absolute()
    assert s.db_path.name == "bist.sqlite"
    assert s.horizons == (1, 3, 5, 10, 20)
    assert s.date("golden_as_of").isoformat() == "2026-09-10"


def test_analytics_thresholds_match_settings() -> None:
    """Analytics are IO-free, so their thresholds are dataclass defaults; they must equal config/settings.yaml."""
    from bistharness.analytics.forward_returns import StudyParams
    from bistharness.analytics.sector import SectorParams

    s = load_settings()
    sp = StudyParams()
    assert sp.horizons == s.horizons
    assert (sp.small_sample, sp.insufficient_sample) == (
        s.threshold("small_sample"),
        s.threshold("insufficient_sample"),
    )
    assert SectorParams().small_group == s.threshold("small_sector_group")
