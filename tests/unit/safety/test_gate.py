import json
from pathlib import Path

import pytest

from argus.config import Settings
from argus.contracts import GateDecision, ProposedAction, Z3Result
from argus.safety import formulation
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


# Commands the parser can't read (patch) go to the Formulation Agent; the LLM is a fake here.


def fake_llm(monkeypatch, answer: dict) -> None:
    def fake_complete_json(prompt, schema, model, timeout_s):
        return json.dumps(answer), {}

    monkeypatch.setattr(formulation, "complete_json", fake_complete_json)


def patch_ir(name: str, effect: str, replicas: int = 0) -> dict:
    return {
        "kind": "deployment",
        "name": name,
        "namespace": "hotel-reservation",
        "effect": effect,
        "replicas": replicas,
    }


@pytest.mark.parametrize(
    ("command", "answer", "decision", "violated"),
    [
        (
            'kubectl patch deployment geo -n hotel-reservation -p \'{"spec":{"replicas":1}}\'',
            patch_ir("geo", "set_replicas", 1),
            GateDecision.BLOCK,
            ["min_replicas"],
        ),
        (
            'kubectl patch deployment geo -n hotel-reservation -p \'{"spec":{"replicas":4}}\'',
            patch_ir("geo", "set_replicas", 4),
            GateDecision.APPROVE,
            [],
        ),
        (
            'kubectl patch deployment frontend -n hotel-reservation -p \'{"spec":{"template":{}}}\'',
            patch_ir("frontend", "pod_template_change"),
            GateDecision.BLOCK,
            ["min_available_during_restart"],
        ),
        (
            'kubectl patch deployment frontend -n hotel-reservation -p \'{"metadata":{"labels":{"t":"x"}}}\'',
            patch_ir("frontend", "metadata_only"),
            GateDecision.APPROVE,
            [],
        ),
    ],
)
def test_patch_goes_through_the_formulation_agent(
    snapshot, monkeypatch, tmp_path, command, answer, decision, violated
):
    fake_llm(monkeypatch, answer)
    settings = Settings(solver_timeout_s=30.0, solver_memory_mb=512, m3_llm_log=str(tmp_path / "llm.jsonl"))
    verdict = check(write(command), snapshot, settings)
    assert verdict.decision is decision
    assert verdict.violated_invariants == violated
    assert "formulation" in verdict.timings_ms


def test_patch_blocks_when_the_llm_is_unreachable(snapshot, tmp_path):
    # No model is set, so the LLM client raises before any network call, and the gate blocks.
    settings = Settings(solver_timeout_s=30.0, solver_memory_mb=512, m3_llm_log=str(tmp_path / "llm.jsonl"))
    command = 'kubectl patch deployment geo -n hotel-reservation -p \'{"spec":{"replicas":4}}\''
    verdict = check(write(command), snapshot, settings)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.reason.startswith("formulation: LLM:")


def test_patch_blocks_when_the_llm_log_cant_be_written(snapshot, monkeypatch, tmp_path):
    # Review on PR #23: the gate itself must block, not raise.
    fake_llm(monkeypatch, patch_ir("geo", "set_replicas", 4))
    settings = Settings(solver_timeout_s=30.0, solver_memory_mb=512, m3_llm_log=str(tmp_path))
    command = 'kubectl patch deployment geo -n hotel-reservation -p \'{"spec":{"replicas":4}}\''
    verdict = check(write(command), snapshot, settings)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.reason.startswith("formulation: can't keep the raw LLM answer")


# The optional trace: what each step did, for the dashboard. It never changes the verdict.


def steps(trace: list) -> list[tuple[str, str]]:
    return [(item["step"], item["status"]) for item in trace]


def test_trace_of_a_checked_scale_lists_every_step_and_the_formula(snapshot):
    trace = []
    verdict = check(
        write("kubectl scale deployment geo --replicas=1 -n hotel-reservation"), snapshot, SETTINGS, trace
    )
    assert steps(trace) == [
        ("Pre-filter", "passed"),
        ("Parse", "passed"),
        ("Cluster facts", "passed"),
        ("Logic compiler + Z3", "passed"),
        ("Decision", "stopped"),
    ]
    solved = trace[3]["data"]
    assert solved["z3_result"] == "sat"
    assert "replicas_after == 1" in solved["formula"]["transition"]
    assert trace[4]["summary"] == "BLOCK: " + verdict.reason


def test_trace_stops_where_m3_stops(snapshot):
    trace = []
    check(write("kubectl get pods -n hotel-reservation | grep geo"), snapshot, SETTINGS, trace)
    assert steps(trace) == [("Pre-filter", "stopped"), ("Decision", "stopped")]


def test_trace_of_a_pod_delete_skips_the_cluster_facts():
    trace = []
    check(write("kubectl delete pod coredns-1 -n kube-system"), None, SETTINGS, trace)
    assert ("Cluster facts", "skipped") in steps(trace)
    assert steps(trace)[-1] == ("Decision", "stopped")


def test_trace_of_a_patch_shows_the_llm_step(snapshot, monkeypatch, tmp_path):
    fake_llm(monkeypatch, patch_ir("geo", "set_replicas", 4))
    settings = Settings(solver_timeout_s=30.0, solver_memory_mb=512, m3_llm_log=str(tmp_path / "llm.jsonl"))
    trace = []
    command = 'kubectl patch deployment geo -n hotel-reservation -p \'{"spec":{"replicas":4}}\''
    check(write(command), snapshot, settings, trace)
    assert steps(trace)[:3] == [("Pre-filter", "passed"), ("Parse", "skipped"), ("LLM formulation", "passed")]
    assert steps(trace)[-1] == ("Decision", "passed")


def test_the_trace_does_not_change_the_verdict(snapshot):
    command = write("kubectl scale deployment geo --replicas=2 -n hotel-reservation")
    without = check(command, snapshot, SETTINGS)
    traced = check(command, snapshot, SETTINGS, [])
    assert traced.decision is without.decision
    assert traced.reason == without.reason
