"""Streamlit UI smoke test on the real snapshot (AppTest runs the script headless)."""

from __future__ import annotations

import pytest

from bistharness.core.config import load_settings, project_root

DB = load_settings().db_path
pytestmark = [pytest.mark.data, pytest.mark.skipif(not DB.exists(), reason="snapshot DB not built")]
APP = str(project_root() / "src" / "bistharness" / "ui" / "app.py")


def test_app_renders_and_runs_a_golden_question() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception
    # select by label: selectbox[0] is the explainer ("template"), the golden question box comes after it
    question = next(s for s in at.sidebar.selectbox if s.label == "Soru")
    question.select("Q5").run()  # the safety question (fast, template explainer: no LLM in this test)
    assert next(s for s in at.sidebar.selectbox if s.label == "Açıklayıcı").value == "template"
    at.sidebar.button[0].click().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "WATCH" in page or "INVESTIGATE" in page
    assert "yatırım tavsiyesi" in page


def test_free_question_with_keyword_understanding() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=300).run()
    next(r for r in at.sidebar.radio if r.label == "Soru kaynağı").set_value("Serbest soru").run()
    next(r for r in at.sidebar.radio if r.label == "Soru anlama").set_value("rules").run()  # no LLM in tests
    assert not at.exception
    assert any("ASELS" in s.value for s in at.sidebar.success)
    at.sidebar.text_area[0].set_value("Erdemir alt banda değince?").run()
    assert any("analiz edilmedi" in w.value for w in at.sidebar.warning)  # keyword rules do not know names
