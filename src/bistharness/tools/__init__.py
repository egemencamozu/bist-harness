"""The 15 MCP tools (CLAUDE.md §6). Importing this package registers every tool in tools.base.REGISTRY."""

from __future__ import annotations

from bistharness.tools import (  # noqa: F401  (imported for registration)
    backtest_tool,
    context,
    evidence_tool,
    fundamentals_tool,
    market,
    quality,
    reversal,
    sector_tool,
    weekday_tool,
)
from bistharness.tools.base import REGISTRY, ToolContext, ToolInputError, run_tool

TOOL_NAMES: tuple[str, ...] = (
    "get_stock_history",
    "get_index_history",
    "calculate_indicators",
    "detect_reversal_events",
    "find_support_resistance",
    "rank_sector_relative_strength",
    "test_weekday_pattern",
    "get_fundamental_metrics",
    "calculate_fundamental_change",
    "get_macro_context",
    "get_news_events",
    "get_speech_features",
    "run_backtest",
    "check_data_quality",
    "build_evidence_bundle",
)

__all__ = ["REGISTRY", "TOOL_NAMES", "ToolContext", "ToolInputError", "run_tool"]
