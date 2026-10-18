"""Fake model fallback outputs still require the real W3-03 gate path."""

import json
from functools import partial
from pathlib import Path
from unittest.mock import Mock

import pytest

from argus.config import Settings
from argus.contracts import DiagnosisResult, ExecutionResult, GateDecision
from argus.orchestration import execution
from argus.orchestration.budget import EstimatedBudget
from argus.orchestration.fake_models import FakeStep, ScriptedAdapter
from argus.orchestration.model_dispatch import DispatchPolicy, dispatch
from argus.orchestration.router import RoutingRequest
from argus.safety.gate import check


@pytest.mark.parametrize("replicas,expected", [(2, GateDecision.APPROVE), (1, GateDecision.BLOCK)])
def test_validated_fallback_actions_still_require_gate_approval(monkeypatch, replicas, expected):
    command = f'  kubectl\t scale deployment "geo" --replicas={replicas} -n hotel-reservation  '
    request = RoutingRequest(
        tasks=[{"task_id": "diagnose", "task_kind": "diagnostic_reasoning", "min_quality": 80}],
        candidates=[
            {
                "task_id": "diagnose",
                "model_id": "primary",
                "layer": "frontier",
                "estimated_cost_units": 1,
                "quality": 85,
            },
            {
                "task_id": "diagnose",
                "model_id": "fallback",
                "layer": "frontier",
                "estimated_cost_units": 2,
                "quality": 90,
            },
        ],
        remaining_budget_units=3,
        objective="min_cost",
        cost_unit="test credits",
        quality_source="synthetic",
    )
    snapshot_path = Path(__file__).resolve().parents[2] / "data/fixtures/m3/snapshot_hotel_reservation.json"
    gate = Mock(
        wraps=partial(
            check,
            snapshot=json.loads(snapshot_path.read_text(encoding="utf-8")),
            settings=Settings(solver_timeout_s=30),
        )
    )
    executor = Mock(
        return_value=ExecutionResult(command=command, executed=False, output="labelled test stub")
    )
    monkeypatch.setattr(execution, "check", gate)
    monkeypatch.setattr(execution, "execute", executor)
    adapter = ScriptedAdapter(
        {
            ("diagnose", "primary"): [FakeStep(error=TimeoutError("simulated"))],
            ("diagnose", "fallback"): [FakeStep({"actions": [{"command": command, "is_write": True}]})],
        }
    )

    result = dispatch(
        request,
        adapter=adapter,
        prompts={"diagnose": "synthetic diagnosis"},
        validators={"diagnose": DiagnosisResult.model_validate},
        policy=DispatchPolicy(
            max_attempts_per_task=2,
            timeout_ms=50,
            retry_on=["timeout"],
            fallbacks=[{"task_id": "diagnose", "model_ids": ["fallback"]}],
        ),
        budget=EstimatedBudget(3, request.cost_unit),
    )

    assert result.tasks[0].status == "succeeded"
    assert result.budget.spent_units == 3
    gate.assert_not_called()
    executor.assert_not_called()
    action = result.tasks[0].output.actions[0]
    assert action.command.encode("utf-8") == command.encode("utf-8")
    handled = execution.handle_action(action)
    assert handled.verdict.decision is expected
    assert gate.call_args.args[0].command == command
    if expected is GateDecision.APPROVE:
        executor.assert_called_once_with(action)
        assert handled.execution.executed is False
    else:
        executor.assert_not_called()
        assert handled.verdict.counterexample["after"] == {"replicas": 1}
