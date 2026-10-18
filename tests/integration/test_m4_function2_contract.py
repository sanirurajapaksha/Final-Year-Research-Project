"""M4 Function 2 entry point consumes/returns the existing shared models."""

import json
from functools import partial
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from argus.config import Settings
from argus.contracts import DiagnosisResult, ExecutionResult, GateDecision, SemanticContext
from argus.orchestration.budget import EstimatedBudget
from argus.orchestration.fake_models import FakeStep, ScriptedAdapter
from argus.orchestration.function2 import run_function2
from argus.orchestration.model_dispatch import DispatchPolicy
from argus.orchestration.router import RoutingRequest
from argus.safety.gate import check


@pytest.fixture
def setup():
    context = SemanticContext(
        anomalies=["geo: café timeout\t🚀"],
        services=["geo", "frontend"],
        dependencies=[("frontend", "geo")],
        notes="recorded fixture, not a live incident",
        symptoms=["HTTP 5xx"],
        failing_services=["geo"],
        entry_point="frontend",
        fallback_used=True,
        strategy="fixture",
        kept_signals=[
            {
                "service": "geo",
                "source": "log",
                "name": "log_error",
                "timestamp": "2026-10-18T00:00:00Z",
                "evidence": "ERROR",
            }
        ],
        nodes=[{"name": "geo", "k8s_status": "Running", "replicas": 3}],
    )
    request = RoutingRequest(
        tasks=[{"task_id": "diagnose", "task_kind": "diagnostic_reasoning", "min_quality": 80}],
        candidates=[
            {
                "task_id": "diagnose",
                "model_id": "primary",
                "layer": "frontier",
                "estimated_cost_units": 2,
                "quality": 85,
            },
            {
                "task_id": "diagnose",
                "model_id": "fallback",
                "layer": "frontier",
                "estimated_cost_units": 3,
                "quality": 90,
            },
        ],
        remaining_budget_units=5,
        objective="min_cost",
        cost_unit="fixture credits",
        quality_source="synthetic",
    )
    return {
        "context": context,
        "request": request,
        "policy": DispatchPolicy(
            max_attempts_per_task=2,
            timeout_ms=50,
            retry_on=["timeout", "invalid_output"],
            fallbacks=[{"task_id": "diagnose", "model_ids": ["fallback"]}],
        ),
        "budget": EstimatedBudget(5, request.cost_unit),
    }


def invoke(setup, adapter, **kwargs):
    return run_function2(**setup, adapter=adapter, **kwargs)


@pytest.mark.parametrize("replicas,decision", [(2, GateDecision.APPROVE), (1, GateDecision.BLOCK)])
@pytest.mark.parametrize("fallback", [False, True])
def test_shared_context_to_diagnosis_gate_execution_and_feedback(setup, replicas, decision, fallback):
    before = setup["context"].model_dump(mode="json")
    read = "kubectl get pods -n hotel-reservation"
    command = f'  kubectl\t scale deployment "geo" --replicas={replicas} -n hotel-reservation  '
    output = {
        "hypotheses": [{"root_cause": "synthetic diagnosis", "probability": 0.9, "evidence": ["fixture"]}],
        "actions": [{"command": read, "is_write": False}, {"command": command, "is_write": True}],
    }
    adapter = ScriptedAdapter(
        {
            ("diagnose", "primary"): [
                FakeStep(error=TimeoutError("simulated")) if fallback else FakeStep(output)
            ],
            ("diagnose", "fallback"): [FakeStep(output)],
        }
    )
    root = Path(__file__).resolve().parents[2]
    snapshot = json.loads(
        (root / "data/fixtures/m3/snapshot_hotel_reservation.json").read_text(encoding="utf-8")
    )
    gate = Mock(wraps=partial(check, snapshot=snapshot, settings=Settings(solver_timeout_s=30)))
    executor = Mock(
        side_effect=lambda action: ExecutionResult(
            command=action.command, executed=False, output="labelled test stub"
        )
    )
    revised = DiagnosisResult(actions=[{"command": "revised command must not run", "is_write": True}])
    feedback = Mock(return_value=revised)

    result = invoke(setup, adapter, gate=gate, executor=executor, feedback_handler=feedback)

    assert result.dispatch.budget.spent_units == (5 if fallback else 2)
    assert len(adapter.calls) == (2 if fallback else 1)
    for call in adapter.calls:
        prompt = json.loads(call.prompt)
        assert prompt == {"output_contract": "DiagnosisResult", "context": before}
    assert setup["context"].model_dump(mode="json") == before
    pipeline = result.pipeline
    assert isinstance(pipeline.context, SemanticContext)
    assert pipeline.context.model_dump(mode="json") == before
    assert pipeline.context is not setup["context"]
    assert isinstance(pipeline.diagnosis, DiagnosisResult)
    assert pipeline.diagnosis.model_dump(mode="json", exclude_unset=True) == output
    gate.assert_called_once()
    assert gate.call_args.args[0].command.encode("utf-8") == command.encode("utf-8")
    assert pipeline.verdicts[0].decision is decision
    assert all(isinstance(item, ExecutionResult) and not item.executed for item in pipeline.executions)
    if decision is GateDecision.APPROVE:
        assert [call.args[0].command for call in executor.call_args_list] == [read, command]
        feedback.assert_not_called()
    else:
        assert [call.args[0].command for call in executor.call_args_list] == [read]
        assert pipeline.verdicts[0].counterexample["after"] == {"replicas": 1}
        feedback.assert_called_once_with(pipeline.context, feedback=[pipeline.verdicts[0]])
        assert pipeline.feedback_diagnosis is revised


@pytest.mark.parametrize("failure", ["infeasible", "invalid_output", "timeouts"])
def test_no_valid_diagnosis_never_reaches_action_handling(setup, failure):
    if failure == "infeasible":
        setup["request"] = RoutingRequest.model_validate(
            {**setup["request"].model_dump(), "remaining_budget_units": 1}
        )
        setup["budget"] = EstimatedBudget(1, setup["request"].cost_unit)
    step = FakeStep({"hypotheses": [{"root_cause": "invalid", "probability": 2}]})
    if failure == "timeouts":
        step = FakeStep(error=TimeoutError("simulated"))
    adapter = ScriptedAdapter({("diagnose", "primary"): [step], ("diagnose", "fallback"): [step]})
    gate, executor, feedback = Mock(), Mock(), Mock()
    result = invoke(setup, adapter, gate=gate, executor=executor, feedback_handler=feedback)
    assert result.pipeline is None
    gate.assert_not_called()
    executor.assert_not_called()
    feedback.assert_not_called()
    if failure == "infeasible":
        assert adapter.calls == ()
        assert result.dispatch.budget.spent_units == 0
    else:
        assert result.dispatch.budget.spent_units == 5
        assert result.dispatch.tasks[0].status == "failed"


def test_invalid_output_can_recover_to_shared_diagnosis(setup):
    adapter = ScriptedAdapter(
        {
            ("diagnose", "primary"): [
                FakeStep({"hypotheses": [{"root_cause": "invalid", "probability": 2}]})
            ],
            ("diagnose", "fallback"): [FakeStep({"hypotheses": [], "actions": []})],
        }
    )
    result = invoke(setup, adapter)
    assert [attempt.status for attempt in result.dispatch.attempts] == ["invalid_output", "success"]
    assert result.pipeline.diagnosis == DiagnosisResult()
    assert result.pipeline.executions == result.pipeline.verdicts == []


@pytest.mark.parametrize("bad_shape", ["empty", "multiple", "parsing"])
def test_task_boundary_is_explicit_and_invalid_shapes_do_not_spend(setup, bad_shape):
    payload = setup["request"].model_dump()
    if bad_shape == "empty":
        payload.update(tasks=[], candidates=[])
    elif bad_shape == "multiple":
        payload["tasks"] = [
            *payload["tasks"],
            {"task_id": "second", "task_kind": "diagnostic_reasoning", "min_quality": 80},
        ]
    else:
        payload["tasks"][0]["task_kind"] = "telemetry_parsing"
    setup["request"] = RoutingRequest.model_validate(payload)
    adapter = ScriptedAdapter({})
    before = setup["budget"].snapshot()
    with pytest.raises(ValueError, match="exactly one"):
        invoke(setup, adapter)
    assert setup["budget"].snapshot() == before
    assert adapter.calls == ()


@pytest.mark.parametrize("bad_context", [None, {}, "not a context"])
def test_entry_requires_the_shared_context_model(setup, bad_context):
    setup["context"] = bad_context
    adapter = ScriptedAdapter({})
    with pytest.raises(TypeError, match="SemanticContext"):
        invoke(setup, adapter)
    assert adapter.calls == ()
    assert setup["budget"].snapshot().spent_units == 0


def test_mutated_invalid_shared_context_is_revalidated_before_calls(setup):
    setup["context"].services = [123]
    adapter = ScriptedAdapter({})
    with pytest.warns(UserWarning), pytest.raises(ValidationError):
        invoke(setup, adapter)
    assert adapter.calls == ()


def test_invalid_feedback_handler_rejected_before_calls(setup):
    adapter = ScriptedAdapter({})
    with pytest.raises(ValueError, match="feedback_handler"):
        invoke(setup, adapter, feedback_handler="not callable")
    assert adapter.calls == ()


@pytest.mark.parametrize("mutated", [False, True])
def test_already_constructed_shared_output_is_revalidated(setup, mutated):
    output = DiagnosisResult(hypotheses=[{"root_cause": "fixture", "probability": 0.9}])
    if mutated:
        output.hypotheses[0].probability = 2
    adapter = ScriptedAdapter(
        {("diagnose", "primary"): [FakeStep(output)], ("diagnose", "fallback"): [FakeStep(output)]}
    )
    result = invoke(setup, adapter)
    if mutated:
        assert result.pipeline is None
        assert [attempt.status for attempt in result.dispatch.attempts] == [
            "invalid_output",
            "invalid_output",
        ]
    else:
        assert result.pipeline.diagnosis == output
        assert result.pipeline.diagnosis is not output


@pytest.mark.parametrize("as_model", [False, True])
def test_invalid_feedback_result_is_visible_and_never_executes_revised_actions(setup, as_model):
    command = "kubectl scale deployment geo --replicas=2 -n hotel-reservation"
    adapter = ScriptedAdapter(
        {("diagnose", "primary"): [FakeStep({"actions": [{"command": command, "is_write": True}]})]}
    )
    executor = Mock()
    if as_model:
        feedback = DiagnosisResult(hypotheses=[{"root_cause": "invalid", "probability": 1}])
        feedback.hypotheses[0].probability = 2
    else:
        feedback = {"hypotheses": [{"root_cause": "invalid", "probability": 2}]}
    handler = Mock(return_value=feedback)
    with pytest.raises(ValidationError):
        invoke(setup, adapter, executor=executor, feedback_handler=handler)
    handler.assert_called_once()
    executor.assert_not_called()
    assert setup["budget"].snapshot().spent_units == 2


def test_default_gate_and_feedback_stub_are_labelled_and_fail_closed(setup):
    command = "kubectl scale deployment geo --replicas=2 -n hotel-reservation"
    adapter = ScriptedAdapter(
        {("diagnose", "primary"): [FakeStep({"actions": [{"command": command, "is_write": True}]})]}
    )
    executor = Mock()
    result = invoke(setup, adapter, executor=executor)
    assert result.pipeline.verdicts[0].decision is GateDecision.BLOCK
    assert "no cluster snapshot" in result.pipeline.verdicts[0].reason
    assert isinstance(result.pipeline.feedback_diagnosis, DiagnosisResult)
    assert result.pipeline.feedback_diagnosis.hypotheses[0].root_cause.startswith("stub:")
    executor.assert_not_called()
