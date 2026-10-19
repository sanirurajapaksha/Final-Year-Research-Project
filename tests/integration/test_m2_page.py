"""The M2 dashboard page, driven by Streamlit's own test runner. Skipped without the 'demo' extra."""

from pathlib import Path

import pytest

from argus.diagnosis.demo import FAKE_READS_LABEL

PAGE = Path(__file__).resolve().parents[2] / "src" / "argus" / "demo" / "pages" / "2_M2_diagnosis.py"

# A small hand-made run, in the shape run_demo() returns. The page only reads its rounds.
RECORD = {
    "incident": "test incident",
    "telemetry_records": 3,
    "context": {"notes": "test notes", "failing_services": ["cart"], "anomalies": []},
    "rounds": [
        {
            "title": "M2 (SIMULATED) proposes",
            "hypotheses": [{"root_cause": "CART_ADDR is missing", "probability": 0.6, "evidence": []}],
            "actions": [],
        }
    ],
}


def run_page():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(PAGE))
    app.session_state["record"] = RECORD
    return app.run(timeout=60)


def test_the_fake_reads_are_labelled():
    app = run_page()
    assert not app.exception
    assert any(FAKE_READS_LABEL in warning.value for warning in app.warning)
    assert any("no LLM" in warning.value for warning in app.warning)


def test_the_summary_shows_the_top_hypothesis():
    app = run_page()
    values = [metric.value for metric in app.metric]
    assert "cart [app-config]" in values
    assert "confident" in values


def test_every_read_has_an_expander():
    app = run_page()
    labels = [expander.label for expander in app.expander]
    assert labels == ["E1 · H1 · ok", "E2 · H2 · ok", "E3 · H3 · ok"]


def test_the_write_is_labelled_and_sent_to_m3():
    app = run_page()
    assert any(markdown.value.startswith("**WRITE**") for markdown in app.markdown)
    assert any("CART_ADDR" in code.value for code in app.code)
    assert any("goes to M3" in caption.value for caption in app.caption)
