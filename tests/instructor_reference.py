"""Loads the instructor's reference functions without importing yfinance/matplotlib.

Only the top-level `def` statements of reference/instructor/<script> are compiled and executed, with numpy/pandas
in their namespace; the download, plotting and print-driven `main` code is never run.
"""

from __future__ import annotations

import ast
from typing import Any

import numpy as np
import pandas as pd

from bistharness.core.config import project_root


def load_reference(script: str, **overrides: Any) -> dict[str, Any]:
    path = project_root() / "reference" / "instructor" / script
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[])
    ns: dict[str, Any] = {"np": np, "pd": pd, "SUCCESS_THRESHOLD": 0.0, "FORWARD_DAYS": 5}
    exec(compile(module, str(path), "exec"), ns)
    ns.update(overrides)  # functions resolve globals at call time -> overrides patch helpers
    return ns


def to_reference_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Our lowercase OHLCV -> the reference's capitalised columns."""
    return df.rename(columns={c: c.capitalize() for c in ("open", "high", "low", "close", "volume")})


S3 = "scenario3_technical_reversal_events_3_periods.py"
S2 = "scenario2_thyao_weekday_patterns.py"
