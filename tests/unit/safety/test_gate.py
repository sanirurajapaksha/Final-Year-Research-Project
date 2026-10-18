from pathlib import Path

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


def test_without_a_snapshot_or_fact_source_a_deployment_write_is_blocked():
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
    verdict = check(write("kubectl label pod geo-1 team=sre -n hotel-reservation"), snapshot, SETTINGS)
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


def test_write_without_a_namespace_is_blocked(snapshot):
    # Regression (PR #14 review): without -n, kubectl uses the current context's namespace,
    # which may be kube-system, so this must not be checked as if it were "default".
    verdict = check(write("kubectl delete pod coredns-1"), snapshot, SETTINGS)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.reason.startswith("parse: missing -n")


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


@pytest.mark.parametrize(
    ("command", "decision", "violated"),
    [
        ("kubectl rollout restart deployment/geo -n hotel-reservation", GateDecision.APPROVE, []),
        ("kubectl rollout restart deployment/profile -n hotel-reservation", GateDecision.APPROVE, []),
        (
            "kubectl rollout restart deployment/frontend -n hotel-reservation",
            GateDecision.BLOCK,
            ["min_available_during_restart"],
        ),
        (
            "kubectl rollout restart deployment/coredns -n kube-system",
            GateDecision.BLOCK,
            ["protected_namespace"],
        ),
    ],
)
def test_rollout_restart(snapshot, command, decision, violated):
    verdict = check(write(command), snapshot, SETTINGS)
    assert verdict.decision is decision
    assert verdict.violated_invariants == violated


def test_restart_with_missing_facts_blocks_and_says_so(snapshot):
    verdict = check(
        write("kubectl rollout restart deployment/search -n hotel-reservation"), snapshot, SETTINGS
    )
    assert verdict.decision is GateDecision.BLOCK
    assert "max_unavailable" in verdict.reason


def test_malformed_max_unavailable_is_blocked():
    bad = {
        "deployments": [
            {"namespace": "hr", "name": "geo", "replicas": 3, "min_replicas": 2, "max_unavailable": "150%"}
        ]
    }
    verdict = check(write("kubectl rollout restart deployment/geo -n hr"), bad, SETTINGS)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.z3_result is None
    assert verdict.reason.startswith("solver:")


def test_restart_solver_timeout_is_blocked(snapshot):
    tiny = Settings(solver_timeout_s=0.001, solver_memory_mb=512)
    verdict = check(write("kubectl rollout restart deployment/geo -n hotel-reservation"), snapshot, tiny)
    assert verdict.decision is GateDecision.BLOCK
    assert "timeout" in verdict.reason


# Facts from the extractor (saved kubectl output) instead of a snapshot passed in.

KUBECTL_OUTPUT = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "m3" / "kubectl"
WITH_EXTRACTOR = Settings(solver_timeout_s=30.0, solver_memory_mb=512, m3_kubectl_output=str(KUBECTL_OUTPUT))


@pytest.mark.parametrize(
    "command",
    [
        "kubectl scale deployment geo --replicas=2 -n hotel-reservation",
        "kubectl scale deployment geo --replicas=1 -n hotel-reservation",
        "kubectl scale deployment search --replicas=2 -n hotel-reservation",
        "kubectl rollout restart deployment/frontend -n hotel-reservation",
        "kubectl delete pvc geo-pvc -n hotel-reservation",
    ],
)
def test_extractor_and_hand_written_snapshot_agree(snapshot, command):
    from_snapshot = check(write(command), snapshot, SETTINGS)
    from_extractor = check(write(command), None, WITH_EXTRACTOR)
    assert from_extractor.decision is from_snapshot.decision
    assert from_extractor.violated_invariants == from_snapshot.violated_invariants
    assert "extractor" in from_extractor.timings_ms


@pytest.mark.parametrize("settings", [WITH_EXTRACTOR, SETTINGS])
@pytest.mark.parametrize(
    "command",
    [
        "kubectl delete pod coredns-7db6d8ff4d-k2l3m -n kube-system",
        "kubectl delete pod x -n kube-public",  # no saved output for kube-public: not needed
        "kubectl delete pod geo-1 -A",
        "kubectl delete ns kube-system",
    ],
)
def test_pod_and_namespace_deletes_skip_the_extractor(command, settings):
    # Their only rule (protected namespaces) needs no cluster facts, so M2 still gets the counterexample.
    verdict = check(write(command), None, settings)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.violated_invariants == ["protected_namespace"]
    assert "extractor" not in verdict.timings_ms


def test_extractor_failure_is_blocked():
    verdict = check(write("kubectl scale deployment geo --replicas=2 -n nowhere"), None, WITH_EXTRACTOR)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.reason.startswith("extractor: LookupError")


def test_a_missing_or_broken_fact_source_is_blocked(tmp_path):
    command = write("kubectl scale deployment geo --replicas=2 -n hotel-reservation")
    missing = Settings(solver_timeout_s=30.0, m3_kubectl_output=str(tmp_path / "missing"))
    verdict = check(command, None, missing)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.reason.startswith("extractor: FileNotFoundError")
    assert "extractor" in verdict.timings_ms

    (tmp_path / "index.json").write_text("{not json", encoding="utf-8")
    broken = Settings(solver_timeout_s=30.0, m3_kubectl_output=str(tmp_path))
    verdict = check(command, None, broken)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.reason.startswith("extractor: JSONDecodeError")


def test_namespace_text_that_adds_flags_is_blocked_before_any_read():
    command = "kubectl scale deployment web --replicas=1 -n 'ns --server=https://other.example'"
    verdict = check(write(command), None, WITH_EXTRACTOR)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.reason.startswith("extractor: ValueError: not a valid namespace name")
