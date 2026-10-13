"""The encodings, checked in-process (hand-written encodings, no generated code).

The gate itself always runs the encodings through the sandbox; see test_gate.py.
"""

import pytest

from argus.safety.compiler import INT32_MAX, EncodingError, solve


def scale_request(replicas: int, facts: dict, namespace: str = "hr") -> dict:
    action = {
        "verb": "scale",
        "kind": "deployment",
        "name": "geo",
        "namespace": namespace,
        "params": {"replicas": replicas},
    }
    return {"action": action, "facts": facts, "timeout_ms": 2000}


def delete_request(kind: str, name: str, namespace: str, facts: dict, params: dict | None = None) -> dict:
    action = {"verb": "delete", "kind": kind, "name": name, "namespace": namespace, "params": params or {}}
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
    request = {"action": {"verb": "patch", "kind": "deployment", "params": {}}, "facts": {}}
    with pytest.raises(EncodingError):
        solve(request)


# I2: protected namespaces


def test_scale_checks_the_protected_namespace_rule():
    assert "protected_namespace" in solve(scale_request(2, HEALTHY))["checked_invariants"]


def test_scale_in_a_protected_namespace_is_sat():
    result = solve(scale_request(5, HEALTHY, namespace="kube-system"))
    assert result["z3_result"] == "sat"
    assert result["violated_invariants"] == ["protected_namespace"]


def test_scale_to_the_same_count_in_a_protected_namespace_is_unsat():
    assert solve(scale_request(3, HEALTHY, namespace="kube-system"))["z3_result"] == "unsat"


def test_scale_in_a_protected_namespace_with_unknown_replicas_is_sat():
    result = solve(scale_request(2, {"min_replicas": 1}, namespace="kube-system"))
    assert result["z3_result"] == "sat"
    assert "protected_namespace" in result["violated_invariants"]


def test_delete_pod_in_an_ordinary_namespace_is_unsat():
    result = solve(delete_request("pod", "geo-1", "hr", {}))
    assert result["z3_result"] == "unsat"
    assert result["checked_invariants"] == ["protected_namespace"]


def test_delete_pod_in_kube_system_is_sat_with_a_counterexample():
    result = solve(delete_request("pod", "coredns-1", "kube-system", {}))
    assert result["z3_result"] == "sat"
    assert result["violated_invariants"] == ["protected_namespace"]
    assert result["counterexample"]["before"] == {"exists": True, "in_protected_namespace": True}
    assert result["counterexample"]["after"] == {"exists": False}


def test_delete_a_protected_namespace_is_sat():
    result = solve(delete_request("namespace", "kube-system", "kube-system", {}))
    assert result["z3_result"] == "sat"
    assert result["violated_invariants"] == ["protected_namespace"]


def test_delete_across_all_namespaces_is_sat():
    result = solve(delete_request("pod", "geo-1", "hr", {}, {"all_namespaces": True}))
    assert result["z3_result"] == "sat"
    assert result["violated_invariants"] == ["protected_namespace"]


# I4: in-use PVC


def test_delete_pvc_in_use_is_sat_with_a_counterexample():
    result = solve(delete_request("pvc", "geo-pvc", "hr", {"in_use": True}))
    assert result["z3_result"] == "sat"
    assert result["violated_invariants"] == ["pvc_in_use"]
    assert result["counterexample"]["before"]["in_use"] is True
    assert result["counterexample"]["after"] == {"exists": False}


def test_delete_pvc_not_in_use_is_unsat():
    result = solve(delete_request("pvc", "old-pvc", "hr", {"in_use": False}))
    assert result["z3_result"] == "unsat"
    assert result["checked_invariants"] == ["protected_namespace", "pvc_in_use"]


def test_delete_pvc_with_unknown_use_is_sat():
    result = solve(delete_request("pvc", "mystery-pvc", "hr", {}))
    assert result["z3_result"] == "sat"
    assert result["missing_facts"] == ["in_use"]
    assert result["counterexample"]["missing_facts_chosen_by_solver"] == ["in_use"]
    assert result["counterexample"]["before"]["in_use"] is True


def test_delete_pvc_in_use_in_kube_system_breaks_both_rules():
    result = solve(delete_request("pvc", "etcd-pvc", "kube-system", {"in_use": True}))
    assert result["z3_result"] == "sat"
    assert result["violated_invariants"] == ["protected_namespace", "pvc_in_use"]


@pytest.mark.parametrize("in_use", ["yes", 1, 0])
def test_in_use_must_be_true_or_false(in_use):
    with pytest.raises(EncodingError):
        solve(delete_request("pvc", "geo-pvc", "hr", {"in_use": in_use}))


# I3: minimum available during a rolling restart


def restart_request(facts: dict, namespace: str = "hr") -> dict:
    action = {
        "verb": "rollout-restart",
        "kind": "deployment",
        "name": "geo",
        "namespace": namespace,
        "params": {},
    }
    return {"action": action, "facts": facts, "timeout_ms": 2000}


def restart_facts(replicas, min_replicas, max_unavailable) -> dict:
    return {"replicas": replicas, "min_replicas": min_replicas, "max_unavailable": max_unavailable}


@pytest.mark.parametrize(
    ("replicas", "min_replicas", "max_unavailable", "z3_result"),
    [
        (3, 2, 1, "unsat"),  # at most 1 down: 2 stay, minimum 2
        (3, 2, 2, "sat"),  # 2 down leaves 1
        (3, 2, 0, "unsat"),  # nothing goes down before its replacement is ready
        (1, 1, 1, "sat"),  # the only pod may go down
        (3, 2, "50%", "unsat"),  # 50% of 3 = 1.5, rounded down to 1
        (2, 2, "50%", "sat"),  # 50% of 2 = 1, leaves 1 of minimum 2
        (2, 1, "25%", "unsat"),  # 25% of 2 = 0.5, rounded down to 0
        (3, 0, 5, "unsat"),  # no minimum: even all pods down is allowed
    ],
)
def test_restart_cases(replicas, min_replicas, max_unavailable, z3_result):
    result = solve(restart_request(restart_facts(replicas, min_replicas, max_unavailable)))
    assert result["z3_result"] == z3_result


def test_unsafe_restart_has_a_counterexample_from_the_range():
    result = solve(restart_request(restart_facts(3, 2, 2)))
    assert result["violated_invariants"] == ["min_available_during_restart"]
    assert result["counterexample"]["during"] == {"pods_down": 2, "available": 1}
    assert result["counterexample"]["before"] == {"replicas": 3, "min_replicas": 2, "max_unavailable": 2}


def test_restart_with_unknown_max_unavailable_is_sat():
    result = solve(restart_request({"replicas": 3, "min_replicas": 2}))
    assert result["z3_result"] == "sat"
    assert result["missing_facts"] == ["max_unavailable"]


def test_percentage_of_unknown_replicas_is_unknown():
    result = solve(restart_request({"min_replicas": 1, "max_unavailable": "25%"}))
    assert result["z3_result"] == "sat"
    assert result["missing_facts"] == ["replicas", "max_unavailable"]


def test_restart_of_an_already_broken_deployment_is_sat_and_reported():
    result = solve(restart_request(restart_facts(0, 2, 1)))
    assert result["z3_result"] == "sat"
    assert result["pre_state_violations"] == ["min_replicas"]


def test_restart_in_a_protected_namespace_is_sat():
    result = solve(restart_request(restart_facts(2, 1, 1), namespace="kube-system"))
    assert result["z3_result"] == "sat"
    assert result["violated_invariants"] == ["protected_namespace"]


@pytest.mark.parametrize("max_unavailable", ["150%", "abc%", "%", "-5%", "abc", -1, True])
def test_malformed_max_unavailable_is_rejected(max_unavailable):
    with pytest.raises(EncodingError):
        solve(restart_request(restart_facts(3, 2, max_unavailable)))
