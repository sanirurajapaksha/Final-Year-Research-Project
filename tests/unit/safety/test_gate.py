import pytest

from argus.config import Settings
from argus.contracts import GateDecision, ProposedAction, Z3Result
from argus.safety.gate import check, decision_for

SETTINGS = Settings(solver_timeout_s=30.0, solver_memory_mb=512)


def write(command: str) -> ProposedAction:
    return ProposedAction(command=command, is_write=True)


@pytest.mark.parametrize(
    ("z3_result", "expected"),
    [
        (Z3Result.UNSAT, GateDecision.APPROVE),
        (Z3Result.SAT, GateDecision.BLOCK),
        (Z3Result.UNKNOWN, GateDecision.BLOCK),
        (None, GateDecision.BLOCK),
    ],
)
def test_decision_mapping_is_fail_closed(z3_result, expected):
    assert decision_for(z3_result) is expected


def test_safe_scale_is_approved(snapshot):
    verdict = check(
        write("kubectl scale deployment geo --replicas=2 -n hotel-reservation"), snapshot, SETTINGS
    )
    assert verdict.decision is GateDecision.APPROVE
    assert verdict.z3_result is Z3Result.UNSAT
    assert verdict.counterexample is None
    assert {"prefilter", "parse", "facts", "sandbox_total", "solver"} <= set(verdict.timings_ms)


def test_unsafe_scale_is_blocked_with_a_counterexample(snapshot):
    verdict = check(
        write("kubectl scale deployment geo --replicas=1 -n hotel-reservation"), snapshot, SETTINGS
    )
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.z3_result is Z3Result.SAT
    assert verdict.violated_invariants == ["min_replicas"]
    assert verdict.counterexample["after"] == {"replicas": 1}


def test_verdict_keeps_the_command_byte_exact(snapshot):
    command = "kubectl  scale deployment geo --replicas=2 -n hotel-reservation "
    assert check(write(command), snapshot, SETTINGS).command == command


def test_without_a_snapshot_everything_is_blocked():
    verdict = check(write("kubectl scale deployment geo --replicas=2 -n hotel-reservation"), None, SETTINGS)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.z3_result is None
    assert "no cluster snapshot" in verdict.reason


def test_unknown_resource_is_blocked(snapshot):
    verdict = check(
        write("kubectl scale deployment ghost --replicas=2 -n hotel-reservation"), snapshot, SETTINGS
    )
    assert verdict.decision is GateDecision.BLOCK
    assert "resource not in snapshot" in verdict.reason


def test_prefilter_rejection_is_blocked(snapshot):
    verdict = check(write("kubectl get pods -n hotel-reservation | grep geo"), snapshot, SETTINGS)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.reason.startswith("pre-filter:")


def test_unsupported_verb_is_blocked(snapshot):
    verdict = check(write("kubectl rollout restart deploy/geo -n hotel-reservation"), snapshot, SETTINGS)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.reason.startswith("parse:")


def test_solver_timeout_is_blocked(snapshot):
    tiny = Settings(solver_timeout_s=0.001, solver_memory_mb=512)
    verdict = check(write("kubectl scale deployment geo --replicas=2 -n hotel-reservation"), snapshot, tiny)
    assert verdict.decision is GateDecision.BLOCK
    assert "timeout" in verdict.reason


@pytest.mark.parametrize(
    ("command", "z3_result", "decision", "violated"),
    [
        ("kubectl delete pod geo-1 -n hotel-reservation", Z3Result.UNSAT, GateDecision.APPROVE, []),
        ("kubectl delete pvc old-pvc -n hotel-reservation", Z3Result.UNSAT, GateDecision.APPROVE, []),
        (
            "kubectl delete pod coredns-1 -n kube-system",
            Z3Result.SAT,
            GateDecision.BLOCK,
            ["protected_namespace"],
        ),
        ("kubectl delete ns kube-system", Z3Result.SAT, GateDecision.BLOCK, ["protected_namespace"]),
        ("kubectl delete pod geo-1 -A", Z3Result.SAT, GateDecision.BLOCK, ["protected_namespace"]),
        ("kubectl delete pvc geo-pvc -n hotel-reservation", Z3Result.SAT, GateDecision.BLOCK, ["pvc_in_use"]),
        (
            "kubectl delete pvc mystery-pvc -n hotel-reservation",
            Z3Result.SAT,
            GateDecision.BLOCK,
            ["pvc_in_use"],
        ),
        (
            "kubectl scale deploy coredns --replicas=0 -n kube-system",
            Z3Result.SAT,
            GateDecision.BLOCK,
            ["min_replicas", "protected_namespace"],
        ),
    ],
)
def test_protected_namespace_and_pvc_rules(snapshot, command, z3_result, decision, violated):
    verdict = check(write(command), snapshot, SETTINGS)
    assert verdict.z3_result is z3_result
    assert verdict.decision is decision
    assert verdict.violated_invariants == violated


def test_deleting_an_unprotected_namespace_is_blocked_without_the_solver(snapshot):
    verdict = check(write("kubectl delete ns hotel-reservation"), snapshot, SETTINGS)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.z3_result is None
    assert "deletes everything in it" in verdict.reason


def test_unknown_pvc_is_blocked(snapshot):
    verdict = check(write("kubectl delete pvc ghost-pvc -n hotel-reservation"), snapshot, SETTINGS)
    assert verdict.decision is GateDecision.BLOCK
    assert "resource not in snapshot: pvc" in verdict.reason


def test_missing_fact_blocks_and_says_so(snapshot):
    verdict = check(
        write("kubectl scale deployment search --replicas=2 -n hotel-reservation"), snapshot, SETTINGS
    )
    assert verdict.decision is GateDecision.BLOCK
    assert "min_replicas" in verdict.reason
