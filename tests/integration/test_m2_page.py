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


def a_report(**changes):
    """A small hand-made report in demo_report()'s shape: M2 found nothing and is unsure."""
    report = {
        "namespace": "default",
        "candidates": [],
        "hypotheses": [],
        "reads": [],
        "belief_rounds": [],
        "stop_reason": "no hypotheses: no candidates",
        "low_confidence": True,
        "diagnosis": {"hypotheses": [], "actions": []},
        "reads_source": FAKE_READS_LABEL,
    }
    report.update(changes)
    return report


@pytest.fixture
def fake_report(monkeypatch):
    """Replace M2's report for one test, with the page's cache cleared before and after."""
    st = pytest.importorskip("streamlit")
    import argus.diagnosis.demo

    def use(report):
        monkeypatch.setattr(argus.diagnosis.demo, "demo_report", lambda context, feedback=None: report)

    st.cache_data.clear()
    yield use
    st.cache_data.clear()


def test_no_hypotheses_shows_none_without_crashing(fake_report):
    fake_report(a_report())
    app = run_page()
    assert not app.exception
    values = [metric.value for metric in app.metric]
    assert "none" in values
    assert "no hypotheses: no candidates" in values
    assert not app.expander


def test_low_confidence_is_flagged(fake_report):
    belief = {"H1": 0.4, "H0": 0.6}
    fake_report(
        a_report(
            hypotheses=[
                {
                    "id": "H1",
                    "component": "cart",
                    "layer": "resources",
                    "fault": "container OOMKilled or crash-looping",
                    "probability": 0.4,
                    "status": "active",
                    "test": "kubectl describe pods -n default -l app=cart",
                    "expected": "OOMKilled",
                }
            ],
            belief_rounds=[{"step": 0, "event": "init", "evidence": "", "verdicts": {}, "belief": belief}],
            stop_reason="budget",
        )
    )
    app = run_page()
    assert not app.exception
    assert any("Low confidence" in warning.value for warning in app.warning)


def test_without_a_block_in_the_run_a_simulated_block_is_shown_and_labelled():
    app = run_page()
    assert not app.exception
    assert any(warning.value.startswith("SIMULATED BLOCK") for warning in app.warning)
    assert any(markdown.value.startswith("Why there is no write now") for markdown in app.markdown)


def test_a_block_from_the_run_is_used_as_is(monkeypatch):
    from argus.context.service import build_context
    from argus.contracts import TelemetryBatch
    from argus.demo.run import TELEMETRY
    from argus.diagnosis.demo import demo_report
    from argus.orchestration.service import compress

    batch = TelemetryBatch.model_validate_json(TELEMETRY.read_text(encoding="utf-8"))
    actions = demo_report(build_context(compress(batch)))["diagnosis"]["actions"]
    fix = [action["command"] for action in actions if action["is_write"]][0]
    verdict = {"command": fix, "decision": "BLOCK", "reason": "test block", "z3_result": "sat"}
    blocked = {"title": "M2 proposes", "hypotheses": [], "actions": [{"command": fix, "verdict": verdict}]}
    monkeypatch.setitem(RECORD, "rounds", [blocked])

    app = run_page()
    assert not app.exception
    assert not any(warning.value.startswith("SIMULATED BLOCK") for warning in app.warning)
    assert any("test block" in markdown.value for markdown in app.markdown)


def test_the_no_cluster_toggle_runs_m2_with_no_reads():
    from argus.diagnosis.demo import NO_READS_LABEL

    app = run_page()
    app.toggle[0].set_value(True).run(timeout=60)
    assert not app.exception
    assert any(NO_READS_LABEL in warning.value for warning in app.warning)
    assert any("Low confidence" in warning.value for warning in app.warning)
    assert all(label.endswith("failed") for label in [expander.label for expander in app.expander])


def test_with_no_reads_the_page_says_why_there_is_no_write():
    app = run_page()
    app.toggle[0].set_value(True).run(timeout=60)
    assert not app.exception
    assert not any(markdown.value.startswith("**WRITE**") for markdown in app.markdown)
    assert any(markdown.value.startswith("No write: the reads did not confirm") for markdown in app.markdown)
