import pytest
from pydantic import ValidationError

from argus.contracts import GateDecision, Hypothesis, ProposedAction, SafetyVerdict


def test_command_is_kept_byte_exact():
    command = 'kubectl  patch deploy geo -n x -p \'{"spec":{"replicas":2}}\'  '
    action = ProposedAction(command=command, is_write=True)
    assert action.command == command


def test_hypothesis_probability_must_be_between_0_and_1():
    with pytest.raises(ValidationError):
        Hypothesis(root_cause="x", probability=1.5)


def test_safety_verdict_requires_a_decision():
    with pytest.raises(ValidationError):
        SafetyVerdict(command="kubectl get pods", reason="missing decision")


def test_safety_verdict_keeps_raw_result_and_decision_separate():
    verdict = SafetyVerdict(command="c", decision=GateDecision.BLOCK, reason="r")
    assert verdict.z3_result is None
    assert verdict.decision is GateDecision.BLOCK
