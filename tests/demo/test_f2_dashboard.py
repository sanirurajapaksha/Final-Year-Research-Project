"""Exercise dashboard wiring across routing, fallback, safety and feedback."""

from pathlib import Path

import pytest

from argus.orchestration.dashboard import scenarios
from argus.orchestration.dashboard.scenarios import routing_demo, safety_demo


def test_routing_controls_and_layer_constraints():
    cheap = routing_demo(20, 70, "min_cost")["plan"]
    strong = routing_demo(20, 70, "max_quality")["plan"]
    assert cheap["total_estimated_cost_units"] == 6
    assert strong["total_estimated_cost_units"] == 11
    assert {item["task_id"]: item["layer"] for item in strong["assignments"]} == {
        "parse": "low_cost",
        "diagnose": "frontier",
    }
    assert routing_demo(5, 70, "max_quality")["plan"]["status"] == "infeasible"
    assert routing_demo(20, 99, "max_quality")["plan"]["status"] == "infeasible"


@pytest.mark.parametrize(
    "failure,status",
    [
        ("Timeout", "timeout"),
        ("Invalid output", "invalid_output"),
        ("Model error", "error"),
        ("Success", "success"),
    ],
)
@pytest.mark.parametrize("replicas,decision", [(1, "BLOCK"), (2, "APPROVE")])
def test_scripted_safety_handoff(failure, status, replicas, decision):
    output = safety_demo(5, failure, replicas)
    assert output["attempts"][0]["status"] == status
    assert output["budget"]["spent_units"] == (2 if failure == "Success" else 5)
    assert output["budget"]["reserved_units"] == 0
    assert output["verdicts"][0]["decision"] == decision
    command = output["diagnosis"]["actions"][1]["command"]
    assert output["verdicts"][0]["command"] == command
    assert all(not execution["executed"] for execution in output["executions"])
    if decision == "BLOCK":
        assert output["feedback_received"][0]["counterexample"]["after"] == {"replicas": 1}
        assert output["feedback_diagnosis"]
        assert len(output["executions"]) == 1
    else:
        assert output["executions"][1]["command"] == command
        assert output["feedback_received"] == []


@pytest.mark.parametrize("budget", [0, 1, 4])
def test_failed_dispatch_stops_before_safety(budget):
    output = safety_demo(budget, "Timeout", 1)
    assert output["diagnosis"] is None
    assert output["verdicts"] == output["executions"] == output["feedback_received"] == []
    assert output["budget"]["spent_units"] == (2 if budget == 4 else 0)
    assert output["budget"]["reserved_units"] == 0
    if budget == 4:
        assert output["tasks"][0]["status"] == "budget_exhausted"


def test_f2_navigation_and_stale_results():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(Path(scenarios.__file__).with_name("app.py")).run(timeout=30)
    app.sidebar.selectbox[0].set_value("Routing & Budget").run()
    assert not app.exception
    assert len(app.dataframe) == 2
    app.slider[0].set_value(0).run()
    assert any("infeasible" in warning.value for warning in app.warning)
    app.sidebar.selectbox[0].set_value("Fallback & Safety").run()
    assert not app.exception
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["5", "0", "0"]
    assert any("BLOCK:" in item.value for item in app.markdown)
    app.main.selectbox[1].set_value(2).run()
    assert not app.metric  # Old BLOCK result must not appear under new controls.
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert any("APPROVE:" in item.value for item in app.markdown)
    app.slider[0].set_value(4).run()
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert any("No valid DiagnosisResult" in warning.value for warning in app.warning)
