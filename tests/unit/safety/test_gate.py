import pytest

from sre_agent.contracts import GateDecision, ProposedAction, Z3Result
from sre_agent.safety.gate import check, decision_for


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


def test_stub_gate_blocks_writes_until_solver_exists():
    action = ProposedAction(command="kubectl scale deployment demo --replicas=0 -n demo", is_write=True)
    verdict = check(action)
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.command == action.command
    assert "prefilter" in verdict.timings_ms
