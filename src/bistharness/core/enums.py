"""Single source of truth for every closed vocabulary in the system."""

from __future__ import annotations

from enum import StrEnum


class AnalyticalAction(StrEnum):
    """The finite action space. The LLM may output exactly one of these and nothing else."""

    HOLD = "HOLD"
    WATCH = "WATCH"
    INVESTIGATE = "INVESTIGATE"
    POTENTIAL_CATCH_UP_CANDIDATE = "POTENTIAL_CATCH_UP_CANDIDATE"
    TECHNICAL_REVERSAL_CANDIDATE = "TECHNICAL_REVERSAL_CANDIDATE"
    FUNDAMENTAL_IMPROVEMENT_CANDIDATE = "FUNDAMENTAL_IMPROVEMENT_CANDIDATE"
    REJECT_SIGNAL = "REJECT_SIGNAL"
    ANALYSIS_UNSAFE = "ANALYSIS_UNSAFE"


CANDIDATE_ACTIONS: frozenset[AnalyticalAction] = frozenset(
    {
        AnalyticalAction.POTENTIAL_CATCH_UP_CANDIDATE,
        AnalyticalAction.TECHNICAL_REVERSAL_CANDIDATE,
        AnalyticalAction.FUNDAMENTAL_IMPROVEMENT_CANDIDATE,
    }
)


class GateStatus(StrEnum):
    """Risk & data-quality gate outcomes, ordered from best to worst."""

    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    INVESTIGATE = "INVESTIGATE"
    ANALYSIS_UNSAFE = "ANALYSIS_UNSAFE"
    HARD_BLOCK = "HARD_BLOCK"


# Which analytical actions remain allowed after each gate outcome (CLAUDE.md §4).
ALLOWED_ACTIONS_BY_GATE: dict[GateStatus, frozenset[AnalyticalAction]] = {
    GateStatus.PASS: frozenset(AnalyticalAction),
    GateStatus.PASS_WITH_WARNINGS: frozenset(AnalyticalAction),
    GateStatus.INVESTIGATE: frozenset(
        {
            AnalyticalAction.INVESTIGATE,
            AnalyticalAction.WATCH,
            AnalyticalAction.REJECT_SIGNAL,
            AnalyticalAction.ANALYSIS_UNSAFE,
        }
    ),
    GateStatus.ANALYSIS_UNSAFE: frozenset({AnalyticalAction.ANALYSIS_UNSAFE}),
    GateStatus.HARD_BLOCK: frozenset({AnalyticalAction.ANALYSIS_UNSAFE}),
}


class ToolStatus(StrEnum):
    OK = "OK"
    OK_WITH_WARNINGS = "OK_WITH_WARNINGS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


class Direction(StrEnum):
    """Hypothesis direction of a research event: bullish events 'succeed' on a positive forward return."""

    BULLISH = "bullish"
    BEARISH = "bearish"


class Severity(StrEnum):
    INFO = "info"
    SOFT = "soft"
    HARD = "hard"


class WarningCode(StrEnum):
    # point-in-time
    END_CLAMPED_TO_AS_OF = "END_CLAMPED_TO_AS_OF"
    AS_OF_BEYOND_DATA = "AS_OF_BEYOND_DATA"
    FORWARD_WINDOW_INCOMPLETE = "FORWARD_WINDOW_INCOMPLETE"
    PRICE_MISSING = "PRICE_MISSING"  # no bar for the instrument on the event / horizon day (e.g. trading halt)
    DISCLOSURE_TIME_UNKNOWN = "DISCLOSURE_TIME_UNKNOWN"
    LOOK_AHEAD = "LOOK_AHEAD"
    FUTURE_FUNDAMENTAL_LEAK = "FUTURE_FUNDAMENTAL_LEAK"
    # sample size / grouping
    SMALL_SAMPLE = "SMALL_SAMPLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    SMALL_SECTOR_GROUP = "SMALL_SECTOR_GROUP"
    STRUCTURAL_LAGGARD = "STRUCTURAL_LAGGARD"  # lags over the long windows too: needs fundamental/macro evidence
    MULTIPLE_TESTING_RISK = "MULTIPLE_TESTING_RISK"
    # price series quality
    OHLC_INCONSISTENT = "OHLC_INCONSISTENT"
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    MISSING_DAY = "MISSING_DAY"
    SUSPICIOUS_JUMP = "SUSPICIOUS_JUMP"
    BROKEN_PRICE_SERIES = "BROKEN_PRICE_SERIES"
    STALE_PRICE = "STALE_PRICE"
    ZERO_VOLUME = "ZERO_VOLUME"
    SOURCE_DISAGREEMENT = "SOURCE_DISAGREEMENT"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    DIVIDENDS_NOT_ADJUSTED = "DIVIDENDS_NOT_ADJUSTED"
    FILLED_FROM_SECONDARY = "FILLED_FROM_SECONDARY"
    ADJUSTMENT_FROM_SECONDARY = "ADJUSTMENT_FROM_SECONDARY"
    PHANTOM_ROW_DROPPED = "PHANTOM_ROW_DROPPED"
    SHORT_HISTORY = "SHORT_HISTORY"
    # fundamentals / macro / context
    TMS29_WARNING = "TMS29_WARNING"
    TMS29_DECUMULATION_APPROX = "TMS29_DECUMULATION_APPROX"
    NOMINAL_VALUES = "NOMINAL_VALUES"  # non-TMS 29 reporter: TRY growth is nominal (inflation / FX translation)
    SHARE_COUNT_APPROX = "SHARE_COUNT_APPROX"  # rights issue after the report: share count for valuation approximate
    NOT_APPLICABLE_FOR_TEMPLATE = "NOT_APPLICABLE_FOR_TEMPLATE"
    MISSING_MACRO = "MISSING_MACRO"
    SPARSE_NEWS = "SPARSE_NEWS"
    LOW_TRANSCRIPT_QUALITY = "LOW_TRANSCRIPT_QUALITY"
    SPEECH_NOT_AVAILABLE = "SPEECH_NOT_AVAILABLE"  # no transcribed segment for the request at as_of
    ENVELOPE_HASH_MISMATCH = "ENVELOPE_HASH_MISMATCH"  # a tool output was altered after it was produced
    PERIOD_MISMATCH = "PERIOD_MISMATCH"
    # fundamentals ingest (KAP XBRL)
    FUNDAMENTAL_REPORT_UNUSABLE = "FUNDAMENTAL_REPORT_UNUSABLE"
    FUNDAMENTAL_UNIT_UNKNOWN = "FUNDAMENTAL_UNIT_UNKNOWN"
    FUNDAMENTAL_COLUMNS_UNVERIFIED = "FUNDAMENTAL_COLUMNS_UNVERIFIED"
    FUNDAMENTAL_VALUE_CONFLICT = "FUNDAMENTAL_VALUE_CONFLICT"
    FUNDAMENTAL_PERIOD_UNMAPPED = "FUNDAMENTAL_PERIOD_UNMAPPED"
    FUNDAMENTALS_COVERAGE_END = "FUNDAMENTALS_COVERAGE_END"


# Codes that force a HARD_BLOCK at the risk gate whenever they appear inside the analysis window.
HARD_BLOCK_CODES: frozenset[WarningCode] = frozenset(
    {
        WarningCode.LOOK_AHEAD,
        WarningCode.FUTURE_FUNDAMENTAL_LEAK,
        WarningCode.BROKEN_PRICE_SERIES,
        WarningCode.NON_POSITIVE_PRICE,
        WarningCode.PERIOD_MISMATCH,
        WarningCode.ENVELOPE_HASH_MISMATCH,
    }
)


class FundamentalTemplate(StrEnum):
    INDUSTRIAL = "industrial"
    BANK = "bank"
    INSURANCE = "insurance"
    BROKERAGE = "brokerage"
    HOLDING = "holding"
    REIT = "reit"


# Industrial ratios that must NOT be computed for financial-institution templates (CLAUDE.md §3).
INDUSTRIAL_ONLY_METRICS: frozenset[str] = frozenset(
    {"ebitda", "ebitda_margin", "net_debt_to_ebitda", "ev_to_ebitda", "current_ratio", "quick_ratio"}
)
FINANCIAL_TEMPLATES: frozenset[FundamentalTemplate] = frozenset(
    {FundamentalTemplate.BANK, FundamentalTemplate.INSURANCE, FundamentalTemplate.BROKERAGE}
)


class HarnessState(StrEnum):
    """Workflow states in their fixed order (config/harness_policy.yaml repeats this order and is checked against it)."""

    START = "START"
    SELECT_UNIVERSE = "SELECT_UNIVERSE"
    LOAD_MARKET_DATA = "LOAD_MARKET_DATA"
    CHECK_DATA_QUALITY = "CHECK_DATA_QUALITY"
    CALCULATE_TECHNICALS = "CALCULATE_TECHNICALS"
    RUN_SECTOR_RELATIVE_ANALYSIS = "RUN_SECTOR_RELATIVE_ANALYSIS"
    RUN_PATTERN_AND_REVERSAL_ANALYSIS = "RUN_PATTERN_AND_REVERSAL_ANALYSIS"
    LOAD_FUNDAMENTALS = "LOAD_FUNDAMENTALS"
    LOAD_MACRO_CONTEXT = "LOAD_MACRO_CONTEXT"
    LOAD_NEWS_AND_SPEECH_CONTEXT = "LOAD_NEWS_AND_SPEECH_CONTEXT"
    BUILD_EVIDENCE = "BUILD_EVIDENCE"
    PREVIEW_STRATEGIES = "PREVIEW_STRATEGIES"
    RUN_BACKTEST = "RUN_BACKTEST"
    RISK_GATE = "RISK_GATE"
    GENERATE_EXPLANATION = "GENERATE_EXPLANATION"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    LOG_AND_CLOSE = "LOG_AND_CLOSE"


class StateStatus(StrEnum):
    DONE = "DONE"
    SKIPPED_NOT_APPLICABLE = "SKIPPED_NOT_APPLICABLE"
    FAILED = "FAILED"


class Scenario(StrEnum):
    S1_SECTOR_CATCH_UP = "S1_SECTOR_CATCH_UP"
    S2_WEEKDAY_PATTERN = "S2_WEEKDAY_PATTERN"
    S3_TECHNICAL_REVERSAL = "S3_TECHNICAL_REVERSAL"
    S4_FUNDAMENTAL_REACTION = "S4_FUNDAMENTAL_REACTION"
    SAFETY_ADVICE_REQUEST = "SAFETY_ADVICE_REQUEST"


class ReviewVerdict(StrEnum):
    ACCEPT = "ACCEPT"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    PENDING = "PENDING"
