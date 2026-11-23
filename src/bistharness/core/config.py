"""Typed access to config/settings.yaml and config/universe.yaml.

The project root can be overridden with the BISTHARNESS_ROOT environment variable (used by tests).
Paths in settings are always resolved relative to the project root, never hard-coded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from bistharness.core.enums import FundamentalTemplate
from bistharness.core.errors import ConfigError


def project_root() -> Path:
    env = os.environ.get("BISTHARNESS_ROOT")
    if env:
        return Path(env).resolve()
    # src/bistharness/core/config.py -> parents[3] is the project root
    return Path(__file__).resolve().parents[3]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"config file is not a mapping: {path}")
    return data


@dataclass(frozen=True)
class Settings:
    root: Path
    raw: dict[str, Any]

    def path(self, *keys: str) -> Path:
        node: Any = self.raw["paths"]
        for k in keys:
            node = node[k]
        p = Path(str(node))
        return p if p.is_absolute() else (self.root / p).resolve()

    def date(self, key: str) -> date:
        return date.fromisoformat(str(self.raw["dates"][key]))

    def threshold(self, key: str) -> float:
        return float(self.raw["thresholds"][key])

    @property
    def horizons(self) -> tuple[int, ...]:
        return tuple(int(h) for h in self.raw["horizons"])

    @property
    def db_path(self) -> Path:
        return self.path("db")

    @property
    def raw_dir(self) -> Path:
        return self.path("raw")

    @property
    def float_decimals(self) -> int:
        return int(self.raw["determinism"]["float_decimals"])

    @property
    def seed(self) -> int:
        return int(self.raw["determinism"]["seed"])


@dataclass(frozen=True)
class Instrument:
    ticker: str
    yahoo: str
    kind: str  # "stock" | "index"
    peer_group: str | None
    template: FundamentalTemplate
    tms29_applies: bool
    course_sector: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Universe:
    active: str
    benchmark: str
    instruments: dict[str, Instrument]
    peer_groups: dict[str, tuple[str, ...]]
    universes: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def tickers(self, universe_id: str | None = None) -> tuple[str, ...]:
        uid = universe_id or self.active
        if uid not in self.universes:
            raise ConfigError(f"unknown universe: {uid}")
        return self.universes[uid]

    def instrument(self, ticker: str) -> Instrument:
        try:
            return self.instruments[ticker]
        except KeyError as exc:
            raise ConfigError(f"unknown ticker: {ticker}") from exc

    def peers(self, ticker: str) -> tuple[str, ...]:
        group = self.instrument(ticker).peer_group
        return self.peer_groups[group] if group else (ticker,)

    def all_stock_tickers(self) -> tuple[str, ...]:
        return tuple(sorted(t for t, i in self.instruments.items() if i.kind == "stock"))


def _build_universe(raw: dict[str, Any]) -> Universe:
    peer_groups = {g: tuple(ts) for g, ts in raw["peer_groups"].items()}
    group_of: dict[str, str] = {}
    for g, ts in peer_groups.items():
        for t in ts:
            if t in group_of:
                raise ConfigError(f"{t} appears in two peer groups: {group_of[t]} and {g}")
            group_of[t] = g

    group_defaults: dict[str, dict[str, Any]] = raw.get("group_defaults", {}) or {}
    overrides: dict[str, dict[str, Any]] = raw.get("ticker_overrides", {}) or {}
    course_sectors: dict[str, str] = raw.get("course_sectors", {}) or {}

    instruments: dict[str, Instrument] = {}
    for ticker, group in group_of.items():
        spec: dict[str, Any] = {"template": "industrial", "tms29_applies": True}
        spec.update(group_defaults.get(group, {}))
        spec.update(overrides.get(ticker, {}))
        instruments[ticker] = Instrument(
            ticker=ticker,
            yahoo=str(spec.get("yahoo", f"{ticker}.IS")),
            kind="stock",
            peer_group=group,
            template=FundamentalTemplate(spec["template"]),
            tms29_applies=bool(spec["tms29_applies"]),
            course_sector=course_sectors.get(ticker),
            aliases=tuple(spec.get("aliases", ())),
        )
    for code, spec in (raw.get("benchmarks") or {}).items():
        instruments[code] = Instrument(
            ticker=code,
            yahoo=str(spec["yahoo"]),
            kind=str(spec.get("kind", "index")),
            peer_group=None,
            template=FundamentalTemplate.INDUSTRIAL,
            tms29_applies=False,
        )

    universes: dict[str, tuple[str, ...]] = {}
    for uid, spec in raw["universes"].items():
        ts = tuple(spec["tickers"]) if "tickers" in spec else tuple(t for g in spec["groups"] for t in peer_groups[g])
        missing = [t for t in ts if t not in instruments]
        if missing:
            raise ConfigError(f"universe {uid} references unknown tickers: {missing}")
        if len(set(ts)) != len(ts):
            raise ConfigError(f"universe {uid} has duplicate tickers")
        universes[uid] = ts

    active = str(raw["active_universe"])
    if active not in universes:
        raise ConfigError(f"active_universe {active} is not defined")
    return Universe(
        active=active,
        benchmark=str(raw["benchmark"]),
        instruments=instruments,
        peer_groups=peer_groups,
        universes=universes,
    )


@lru_cache(maxsize=4)
def load_settings(root: Path | None = None) -> Settings:
    r = (root or project_root()).resolve()
    return Settings(root=r, raw=_read_yaml(r / "config" / "settings.yaml"))


@lru_cache(maxsize=4)
def load_universe(root: Path | None = None) -> Universe:
    r = (root or project_root()).resolve()
    return _build_universe(_read_yaml(r / "config" / "universe.yaml"))


def universe_from_dict(raw: dict[str, Any]) -> Universe:
    """Build a Universe from an in-memory mapping (tests, ad-hoc universes)."""
    return _build_universe(raw)


def read_config_yaml(name: str, root: Path | None = None) -> dict[str, Any]:
    """Read config/<name> (e.g. 'harness_policy.yaml') from the project root."""
    return _read_yaml((root or project_root()).resolve() / "config" / name)
