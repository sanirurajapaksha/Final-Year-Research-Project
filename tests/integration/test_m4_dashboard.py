"""Exercise M4's page controls using the same saved-run shape as the app."""

from pathlib import Path

import pytest

from argus.demo.scenario import simulated_diagnose
from argus.orchestration.pipeline import run_once
from argus.orchestration.report import load_scenario


def table_with_columns(app, *columns):
    matches = [table.value for table in app.table if set(columns) == set(table.value.columns)]
    assert len(matches) == 1, f"Expected one table with columns {columns}, found {len(matches)}"
    return matches[0]


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
    attempts = table_with_columns(app, "task_id", "model_id", "status", "charged_estimated_units", "reason")
    assert (attempts["model_id"] == "fake-fallback").any()
    app.slider[0].set_value(4).run(timeout=60)
    assert not app.exception
    tasks = table_with_columns(app, "task_id", "status", "reason")
    assert (tasks["status"] == "budget_exhausted").any()
    app.slider[0].set_value(1).run(timeout=60)
    assert not app.exception
    assert app.warning
