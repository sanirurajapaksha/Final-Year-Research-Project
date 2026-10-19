"""Exercise M4's page controls using the same saved-run shape as the app."""

from pathlib import Path

import pytest

from argus.demo.scenario import simulated_diagnose
from argus.orchestration.pipeline import run_once
from argus.orchestration.report import load_scenario


def test_m4_page_compression_fallback_and_budget_stop():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    result = run_once(load_scenario(), diagnoser=simulated_diagnose)
    diagnosis = result.diagnosis.model_dump(mode="json")
    actions = []
    for action in diagnosis["actions"]:
        action.update(verdict=None, execution=None)
        actions.append(action)
    record = {
        "context": result.context.model_dump(mode="json"),
        "rounds": [{"title": "SIMULATED", "hypotheses": diagnosis["hypotheses"], "actions": actions}],
    }
    path = Path(__file__).resolve().parents[2] / "src/argus/demo/pages/4_M4_orchestration.py"
    app = AppTest.from_file(str(path))
    app.session_state["record"] = record
    app.run(timeout=60)
    assert not app.exception
    assert app.metric[0].label == "Original JSON bytes"
    assert "fake-fallback" in app.table[3].value.to_string()
    app.slider[0].set_value(4).run(timeout=60)
    assert not app.exception
    assert "budget_exhausted" in app.table[4].value.to_string()
    app.slider[0].set_value(1).run(timeout=60)
    assert not app.exception
    assert app.warning
