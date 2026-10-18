import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError

from argus.orchestration import model_dispatch
from argus.orchestration.budget import EstimatedBudget
from argus.orchestration.fake_models import FakeStep, ScriptedAdapter
from argus.orchestration.model_dispatch import AdapterReply, DispatchPolicy, dispatch
from argus.orchestration.router import RoutingPlan, RoutingRequest

FIXTURE = Path(__file__).resolve().parents[3] / "data/fixtures/m4/routing_synthetic.json"


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: StrictStr


@pytest.fixture
def setup():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.update(objective="min_cost", remaining_budget_units=17)
    request = RoutingRequest.model_validate(payload)
    policy = DispatchPolicy(
        max_attempts_per_task=2,
        timeout_ms=50,
        retry_on=("timeout", "error", "invalid_output"),
        fallbacks=(
            {"task_id": "diagnose", "model_ids": ["fixture-frontier-b"]},
            {"task_id": "parse", "model_ids": ["fixture-low-b"]},
        ),
    )
    ledger = EstimatedBudget(17, request.cost_unit)
    return {
        "request": request,
        "policy": policy,
        "budget": ledger,
        "prompts": {"diagnose": "diagnose\twithout rewriting\n", "parse": "parse this telemetry"},
        "validators": {"diagnose": Output.model_validate, "parse": Output.model_validate},
    }


def run(setup, adapter):
    return dispatch(setup["request"], adapter=adapter, **{k: v for k, v in setup.items() if k != "request"})


def successful_scripts():
    return {
        ("diagnose", "fixture-frontier-a"): [FakeStep({"text": "diagnosis"})],
        ("parse", "fixture-low-a"): [FakeStep({"text": "parsed"})],
    }


def test_selected_models_are_called_once_with_exact_prompts(setup):
    adapter = ScriptedAdapter(successful_scripts())
    result = run(setup, adapter)
    assert result.plan.status == "optimal"
    assert [task.status for task in result.tasks] == ["succeeded", "succeeded"]
    assert [task.output.text for task in result.tasks] == ["diagnosis", "parsed"]
    assert [(call.task_id, call.model_id) for call in adapter.calls] == [
        ("diagnose", "fixture-frontier-a"),
        ("parse", "fixture-low-a"),
    ]
    assert adapter.calls[0].prompt == setup["prompts"]["diagnose"]
    assert all(call.timeout_ms == 50 for call in adapter.calls)
    assert result.budget.spent_units == 6
    assert result.budget.available_units == 11
    assert result.budget.reserved_units == 0


@pytest.mark.parametrize("failure", ["timeout", "error", "invalid_output", "late_reply", "malformed_reply"])
def test_failure_falls_back_and_charges_both_attempts(setup, failure):
    if failure == "timeout":
        first = FakeStep({"text": "late"}, elapsed_ms=51)
    elif failure == "error":
        first = FakeStep(error=RuntimeError("injected error"))
    else:
        first = FakeStep({"wrong": "schema"})
    scripts = successful_scripts()
    scripts[("diagnose", "fixture-frontier-a")] = [first]
    scripts[("diagnose", "fixture-frontier-b")] = [FakeStep({"text": "fallback"})]
    adapter = ScriptedAdapter(scripts)
    if failure in ("late_reply", "malformed_reply"):
        original = adapter.call

        def broken_reply(task, candidate, prompt, **kwargs):
            if candidate.model_id == "fixture-frontier-a":
                return AdapterReply({"text": "late"}, 51) if failure == "late_reply" else None
            return original(task, candidate, prompt, **kwargs)

        adapter.call = broken_reply
    result = run(setup, adapter)
    expected = (
        "timeout"
        if failure in ("timeout", "late_reply")
        else "error"
        if failure == "error"
        else "invalid_output"
    )
    assert [attempt.status for attempt in result.attempts] == [expected, "success", "success"]
    assert result.tasks[0].output.text == "fallback"
    assert result.budget.spent_units == 13
    assert result.budget.available_units == 4
    assert result.budget.reserved_units == 0


def test_initial_reservations_prevent_fallback_from_starving_another_task(setup):
    setup["request"] = RoutingRequest.model_validate(
        {**setup["request"].model_dump(), "remaining_budget_units": 11}
    )
    setup["budget"] = EstimatedBudget(11, setup["request"].cost_unit)
    scripts = successful_scripts()
    scripts[("diagnose", "fixture-frontier-a")] = [FakeStep(error=TimeoutError("failure"))]
    scripts[("diagnose", "fixture-frontier-b")] = [FakeStep({"text": "must not be called"})]
    adapter = ScriptedAdapter(scripts)
    result = run(setup, adapter)
    # After the first charge, 7 units remain, but 2 are held for parsing: fallback cost 7 cannot fit.
    assert [task.status for task in result.tasks] == ["budget_exhausted", "succeeded"]
    assert [call.model_id for call in adapter.calls] == ["fixture-frontier-a", "fixture-low-a"]
    assert result.budget.spent_units == 6
    assert result.budget.available_units == 5


@pytest.mark.parametrize("stop_by", ["attempt_limit", "retry_condition", "no_fallback"])
def test_configured_policy_can_stop_fallback(setup, stop_by):
    policy = setup["policy"].model_dump()
    if stop_by == "attempt_limit":
        policy["max_attempts_per_task"] = 1
    elif stop_by == "retry_condition":
        policy["retry_on"] = ["timeout"]
    else:
        policy["fallbacks"] = []
    setup["policy"] = DispatchPolicy.model_validate(policy)
    scripts = successful_scripts()
    scripts[("diagnose", "fixture-frontier-a")] = [FakeStep(error=RuntimeError("error"))]
    adapter = ScriptedAdapter(scripts)
    result = run(setup, adapter)
    assert result.tasks[0].status == "failed"
    assert len(result.attempts) == 2
    assert result.budget.spent_units == 6


def test_explicit_same_model_retry_and_retry_exhaustion(setup):
    policy = setup["policy"].model_dump()
    policy["fallbacks"] = [{"task_id": "diagnose", "model_ids": ["fixture-frontier-a", "fixture-frontier-b"]}]
    setup["policy"] = DispatchPolicy.model_validate(policy)
    scripts = successful_scripts()
    scripts[("diagnose", "fixture-frontier-a")] = [FakeStep(error=TimeoutError("retry"))] * 2
    adapter = ScriptedAdapter(scripts)
    result = run(setup, adapter)
    assert result.tasks[0].status == "failed"
    assert [attempt.model_id for attempt in result.attempts] == [
        "fixture-frontier-a",
        "fixture-frontier-a",
        "fixture-low-a",
    ]
    assert result.budget.spent_units == 10


def test_ledger_persists_across_batches_and_failed_calls_are_not_refunded(setup):
    first = run(setup, ScriptedAdapter(successful_scripts()))
    assert first.budget.available_units == 11
    setup["request"] = RoutingRequest.model_validate(
        {**setup["request"].model_dump(), "remaining_budget_units": 11}
    )
    second = run(setup, ScriptedAdapter(successful_scripts()))
    assert second.budget.spent_units == 12
    assert second.budget.available_units == 5
    setup["request"] = RoutingRequest.model_validate(
        {**setup["request"].model_dump(), "remaining_budget_units": 5}
    )
    adapter = ScriptedAdapter({})
    third = run(setup, adapter)
    assert third.plan.status == "infeasible"
    assert third.budget == second.budget
    assert third.attempts == third.tasks == ()
    assert adapter.calls == ()


@pytest.mark.parametrize(
    "problem",
    [
        "wrong_layer",
        "low_quality",
        "unknown_model",
        "unknown_task",
        "missing_prompt",
        "missing_validator",
        "bad_unit",
        "stale_budget",
    ],
)
def test_invalid_configuration_fails_before_calls_or_reservations(setup, problem):
    if problem in ("wrong_layer", "low_quality", "unknown_model", "unknown_task"):
        policy = setup["policy"].model_dump()
        rule = policy["fallbacks"][0]
        if problem == "wrong_layer":
            rule["model_ids"] = ["fixture-low-a"]
        elif problem == "unknown_model":
            rule["model_ids"] = ["missing"]
        elif problem == "unknown_task":
            rule["task_id"] = "missing"
        else:
            payload = setup["request"].model_dump()
            for candidate in payload["candidates"]:
                if candidate["model_id"] == "fixture-frontier-b":
                    candidate["quality"] = 0
            setup["request"] = RoutingRequest.model_validate(payload)
        setup["policy"] = DispatchPolicy.model_validate(policy)
    elif problem == "missing_prompt":
        setup["prompts"].pop("parse")
    elif problem == "missing_validator":
        setup["validators"].pop("parse")
    elif problem == "bad_unit":
        setup["budget"] = EstimatedBudget(17, "other units")
    else:
        setup["budget"].charge(setup["budget"].reserve(1))
    before = setup["budget"].snapshot()
    adapter = ScriptedAdapter(successful_scripts())
    with pytest.raises(ValueError):
        run(setup, adapter)
    assert setup["budget"].snapshot() == before
    assert adapter.calls == ()


def test_solver_error_makes_no_calls(setup, monkeypatch):
    monkeypatch.setattr(model_dispatch, "route", Mock(return_value=RoutingPlan(status="solver_error")))
    adapter = ScriptedAdapter({})
    result = run(setup, adapter)
    assert result.plan.status == "solver_error"
    assert result.tasks == result.attempts == ()
    assert result.budget.spent_units == result.budget.reserved_units == 0
    assert adapter.calls == ()


def test_interrupt_releases_unstarted_reservations_but_keeps_started_charge(setup):
    adapter = Mock()
    adapter.call.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run(setup, adapter)
    assert setup["budget"].snapshot().spent_units == 4
    assert setup["budget"].snapshot().reserved_units == 0


def test_unrelated_reservations_are_preserved(setup):
    ledger = EstimatedBudget(19, setup["request"].cost_unit)
    external = ledger.reserve(2)
    setup["budget"] = ledger
    result = run(setup, ScriptedAdapter(successful_scripts()))
    assert result.budget.spent_units == 6
    assert result.budget.reserved_units == 2
    assert result.budget.available_units == 11
    ledger.release(external)
    assert ledger.snapshot().available_units == 13


def test_empty_batch_leaves_the_ledger_unchanged(setup):
    setup["request"] = RoutingRequest.model_validate(
        {**setup["request"].model_dump(), "tasks": [], "candidates": []}
    )
    setup["prompts"] = setup["validators"] = {}
    setup["policy"] = DispatchPolicy(max_attempts_per_task=1, timeout_ms=50, retry_on=[], fallbacks=[])
    before = setup["budget"].snapshot()
    adapter = ScriptedAdapter({})
    result = run(setup, adapter)
    assert result.plan.status == "optimal"
    assert result.tasks == result.attempts == ()
    assert result.budget == before
    assert adapter.calls == ()


def test_invalid_adapter_does_not_consume_budget(setup):
    before = setup["budget"].snapshot()
    with pytest.raises(ValueError, match="adapter"):
        run(setup, object())
    assert setup["budget"].snapshot() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("timeout_ms", 0),
        ("max_attempts_per_task", True),
        ("retry_on", ["anything"]),
        ("fallbacks", [{"task_id": "parse", "model_ids": []}] * 2),
    ],
)
def test_invalid_policy_rejected(setup, field, value):
    payload = setup["policy"].model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        DispatchPolicy.model_validate(payload)
