"""The five golden questions end to end through the harness with the deterministic template explainer (real
snapshot; skipped when the DB is missing). The LLM run is the same suite: uv run python -m eval.run_golden --explainer llm
"""

from __future__ import annotations

from datetime import date

import pytest

from bistharness.core.config import load_settings
from bistharness.harness.factory import build_config, tool_context
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.runner import run_analysis
from eval.run_golden import check, load_golden, request_of

DB = load_settings().db_path
pytestmark = [pytest.mark.data, pytest.mark.skipif(not DB.exists(), reason="snapshot DB not built")]
GOLDEN = load_golden()


@pytest.mark.parametrize("q", GOLDEN["questions"], ids=[q["id"] for q in GOLDEN["questions"]])
def test_golden_question(q: dict) -> None:
    res = run_analysis(
        request_of(q, date.fromisoformat(GOLDEN["as_of_date"])),
        tool_context(),
        build_config(explainer="template", memory=EpisodicMemory()),
    )
    checks = check(q, res)
    assert all(checks.values()), {k: v for k, v in checks.items() if not v}
