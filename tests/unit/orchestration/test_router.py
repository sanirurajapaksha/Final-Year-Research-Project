"""Offline routing optima checked by independent exhaustive enumeration."""

import itertools
import json
import random
from pathlib import Path

import pytest
import z3
from pydantic import ValidationError

from argus.orchestration import router
from argus.orchestration.router import RoutingRequest, route

FIXTURE = Path(__file__).resolve().parents[3] / "data/fixtures/m4/routing_synthetic.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def oracle(request):
    """Enumerate whole assignments and rank by the declared lexicographic policy."""
    tasks = sorted(request.tasks, key=lambda task: task.task_id)
    candidates = []
    for task in tasks:
        required = "low_cost" if task.task_kind == "telemetry_parsing" else "frontier"
        candidates.append(
            [
                candidate
                for candidate in request.candidates
                if candidate.task_id == task.task_id
                and candidate.layer == required
                and candidate.quality >= task.min_quality
            ]
        )
    feasible = []
    for combination in itertools.product(*candidates):
        cost = sum(candidate.estimated_cost_units for candidate in combination)
        quality = sum(candidate.quality for candidate in combination)
        if cost <= request.remaining_budget_units:
            objectives = (-quality, cost) if request.objective == "max_quality" else (cost, -quality)
            feasible.append(((*objectives, tuple(c.model_id for c in combination)), combination))
    return min(feasible, key=lambda item: item[0])[1] if feasible else None


@pytest.mark.parametrize("budget", [0, 5, 6, 8, 9, 11, 100])
@pytest.mark.parametrize("objective", ["max_quality", "min_cost"])
def test_optimum_matches_enumeration(payload, budget, objective):
    payload.update(remaining_budget_units=budget, objective=objective)
    request = RoutingRequest.model_validate(payload)
    before = request.model_dump_json()
    expected = oracle(request)

    plan = route(request)

    assert request.model_dump_json() == before
    if expected is None:
        assert plan.status == "infeasible"
        assert plan.assignments == ()
        assert plan.total_estimated_cost_units == plan.total_estimated_quality == 0
    else:
        assert plan.status == "optimal"
        assert plan.assignments == expected
        assert plan.total_estimated_cost_units == sum(c.estimated_cost_units for c in expected)
        assert plan.total_estimated_quality == sum(c.quality for c in expected)


def test_shared_budget_requires_a_global_choice(payload):
    plan = route(RoutingRequest.model_validate(payload))
    assert plan.status == "optimal"
    assert [(c.task_id, c.model_id) for c in plan.assignments] == [
        ("diagnose", "fixture-frontier-a"),
        ("parse", "fixture-low-b"),
    ]
    assert plan.total_estimated_cost_units == 8
    assert plan.total_estimated_quality == 175


def test_taf_layers_override_cheaper_high_scoring_candidates(payload):
    payload["remaining_budget_units"] = 100
    plan = route(RoutingRequest.model_validate(payload))
    assert plan.status == "optimal"
    assert {c.task_id: c.layer for c in plan.assignments} == {"parse": "low_cost", "diagnose": "frontier"}
    assert plan.total_estimated_quality == 188


def test_deterministic_ties_ignore_input_order(payload):
    for candidate in payload["candidates"]:
        candidate.update(estimated_cost_units=1, quality=100)
    expected = route(RoutingRequest.model_validate(payload))
    payload["tasks"].reverse()
    payload["candidates"].reverse()
    assert route(RoutingRequest.model_validate(payload)) == expected
    assert [c.model_id for c in expected.assignments] == ["fixture-frontier-a", "fixture-low-a"]


@pytest.mark.parametrize("objective", ["max_quality", "min_cost"])
def test_random_small_batches_match_enumeration(payload, objective):
    rng = random.Random(305)
    for _ in range(12):
        for candidate in payload["candidates"]:
            candidate.update(estimated_cost_units=rng.randint(0, 12), quality=rng.randint(0, 100))
        payload.update(remaining_budget_units=rng.randint(0, 24), objective=objective)
        request = RoutingRequest.model_validate(payload)
        expected = oracle(request)
        plan = route(request)
        assert plan.status == ("infeasible" if expected is None else "optimal")
        assert plan.assignments == (() if expected is None else expected)


def test_empty_batch(payload):
    payload.update(tasks=[], candidates=[], remaining_budget_units=0)
    plan = route(RoutingRequest.model_validate(payload))
    assert plan.status == "optimal"
    assert plan.assignments == ()
    assert plan.total_estimated_cost_units == 0


def test_zero_cost_candidates_fit_a_zero_budget(payload):
    payload["remaining_budget_units"] = 0
    for candidate in payload["candidates"]:
        candidate["estimated_cost_units"] = 0
    plan = route(RoutingRequest.model_validate(payload))
    assert plan.status == "optimal"
    assert len(plan.assignments) == 2
    assert plan.total_estimated_cost_units == 0
    assert plan.total_estimated_quality == 188


@pytest.mark.parametrize("objective", ["max_quality", "min_cost"])
def test_secondary_objectives_are_applied(payload, objective):
    payload.update(objective=objective, remaining_budget_units=100)
    if objective == "max_quality":
        for candidate in payload["candidates"]:
            candidate["quality"] = 100
    else:
        for candidate in payload["candidates"]:
            candidate["estimated_cost_units"] = 1
    request = RoutingRequest.model_validate(payload)
    plan = route(request)
    assert plan.status == "optimal"
    assert plan.assignments == oracle(request)
    if objective == "max_quality":
        assert plan.total_estimated_cost_units == 6
    else:
        assert plan.total_estimated_quality == 188


@pytest.mark.parametrize("missing", ["no_candidates", "wrong_layer", "below_quality"])
def test_no_eligible_candidate_is_infeasible(payload, missing):
    if missing == "no_candidates":
        payload["candidates"] = []
    elif missing == "wrong_layer":
        payload["candidates"] = [c for c in payload["candidates"] if c["layer"] == "low_cost"]
    else:
        for candidate in payload["candidates"]:
            candidate["quality"] = 0
    plan = route(RoutingRequest.model_validate(payload))
    assert plan.status == "infeasible"
    assert plan.assignments == ()


@pytest.mark.parametrize("value", [-1, 1.5, "9", True])
def test_invalid_budget_rejected(payload, value):
    payload["remaining_budget_units"] = value
    with pytest.raises(ValidationError):
        RoutingRequest.model_validate(payload)


@pytest.mark.parametrize("field,value", [("quality", 101), ("quality", -1), ("estimated_cost_units", 0.5)])
def test_invalid_candidate_numbers_rejected(payload, field, value):
    payload["candidates"][0][field] = value
    with pytest.raises(ValidationError):
        RoutingRequest.model_validate(payload)


@pytest.mark.parametrize("problem", ["duplicate_task", "duplicate_pair", "unknown_task", "conflicting_layer"])
def test_invalid_references_rejected(payload, problem):
    if problem == "duplicate_task":
        payload["tasks"].append(payload["tasks"][0])
    elif problem == "duplicate_pair":
        payload["candidates"].append(payload["candidates"][0])
    elif problem == "unknown_task":
        payload["candidates"][0]["task_id"] = "missing"
    else:
        payload["candidates"][-1]["layer"] = "frontier"
    with pytest.raises(ValidationError):
        RoutingRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["objective", "cost_unit", "quality_source"])
def test_policy_and_provenance_are_required(payload, field):
    del payload[field]
    with pytest.raises(ValidationError):
        RoutingRequest.model_validate(payload)


def test_unknown_fields_are_not_silently_ignored(payload):
    payload["budget"] = 999
    with pytest.raises(ValidationError):
        RoutingRequest.model_validate(payload)


@pytest.mark.parametrize("timeout", [0, -1, 1.5, True])
def test_invalid_solver_timeout_rejected(payload, timeout):
    with pytest.raises(ValueError, match="positive integer"):
        route(RoutingRequest.model_validate(payload), timeout_ms=timeout)


@pytest.mark.parametrize("failure", ["unknown", "exception", "unproven"])
def test_solver_failures_return_no_plan(payload, monkeypatch, failure):
    original = z3.Optimize

    def failed_solver(*args, **kwargs):
        solver = original(*args, **kwargs)
        if failure == "unknown":
            solver.check = lambda: z3.unknown
            solver.reason_unknown = lambda: "injected timeout"
        elif failure == "exception":

            def raise_error():
                raise z3.Z3Exception("injected solver error")

            solver.check = raise_error
        else:
            real_maximize = solver.maximize

            def unproven(expression):
                handle = real_maximize(expression)
                handle.lower = lambda: z3.IntVal(0)
                handle.upper = lambda: z3.IntVal(1)
                return handle

            solver.maximize = unproven
        return solver

    monkeypatch.setattr(router.z3, "Optimize", failed_solver)
    plan = route(RoutingRequest.model_validate(payload))
    assert plan.status == "solver_error"
    assert plan.assignments == ()
    assert plan.total_estimated_cost_units == plan.total_estimated_quality == 0
    assert plan.reason
