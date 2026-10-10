"""The min-replicas encoding, checked in-process (hand-written encoding, no generated code).

The gate itself always runs the encoding through the sandbox; see test_gate.py.
"""

import pytest

from argus.safety.compiler import INT32_MAX, EncodingError, solve


def scale_request(replicas: int, facts: dict) -> dict:
    action = {
        "verb": "scale",
        "kind": "deployment",
        "name": "geo",
        "namespace": "hr",
        "params": {"replicas": replicas},
    }
    return {"action": action, "facts": facts, "timeout_ms": 2000}


HEALTHY = {"replicas": 3, "min_replicas": 2}


def test_safe_scale_down_to_the_minimum_is_unsat():
    result = solve(scale_request(2, HEALTHY))
    assert result["z3_result"] == "unsat"
    assert result["counterexample"] is None


def test_unsafe_scale_below_the_minimum_is_sat_with_a_counterexample():
    result = solve(scale_request(1, HEALTHY))
    assert result["z3_result"] == "sat"
    assert result["violated_invariants"] == ["min_replicas"]
    assert result["counterexample"]["before"] == {"replicas": 3, "min_replicas": 2}
    assert result["counterexample"]["after"] == {"replicas": 1}


def test_scale_to_zero_is_sat():
    assert solve(scale_request(0, HEALTHY))["z3_result"] == "sat"


def test_negative_replicas_break_the_int32_range():
    result = solve(scale_request(-1, HEALTHY))
    assert result["z3_result"] == "sat"
    assert "replicas_in_int32_range" in result["violated_invariants"]


def test_overflow_past_int32_is_sat():
    result = solve(scale_request(INT32_MAX + 1, HEALTHY))
    assert result["z3_result"] == "sat"
    assert result["violated_invariants"] == ["replicas_in_int32_range"]


def test_int32_max_itself_is_allowed():
    assert solve(scale_request(INT32_MAX, HEALTHY))["z3_result"] == "unsat"


def test_missing_min_replicas_is_left_to_the_solver_and_blocks():
    result = solve(scale_request(2, {"replicas": 2}))
    assert result["z3_result"] == "sat"
    assert result["counterexample"]["missing_facts_chosen_by_solver"] == ["min_replicas"]


def test_missing_current_replicas_does_not_matter_for_scale():
    result = solve(scale_request(2, {"min_replicas": 2}))
    assert result["z3_result"] == "unsat"
    assert result["missing_facts"] == ["replicas"]


def test_already_broken_cluster_is_not_a_free_pass():
    broken = {"replicas": 0, "min_replicas": 2}
    still_broken = solve(scale_request(1, broken))
    assert still_broken["z3_result"] == "sat"
    assert still_broken["pre_state_violations"] == ["min_replicas"]
    fixed = solve(scale_request(2, broken))
    assert fixed["z3_result"] == "unsat"
    assert fixed["pre_state_violations"] == ["min_replicas"]


@pytest.mark.parametrize(
    "facts",
    [
        {"replicas": 3, "min_replicas": -1},
        {"replicas": INT32_MAX + 1, "min_replicas": 2},
        {"replicas": "3", "min_replicas": 2},
        {"replicas": True, "min_replicas": 2},
    ],
)
def test_malformed_facts_are_rejected(facts):
    with pytest.raises(EncodingError):
        solve(scale_request(2, facts))


def test_unknown_action_is_rejected():
    request = {"action": {"verb": "delete", "kind": "pod", "params": {}}, "facts": {}}
    with pytest.raises(EncodingError):
        solve(request)
