"""W3-03: real M3 gate, recorded facts, and a recording execution stub."""

import json
from functools import partial
from pathlib import Path
from unittest.mock import Mock

import pytest

from argus.config import Settings
from argus.contracts import (
    DiagnosisResult,
    ExecutionResult,
    GateDecision,
    ProposedAction,
    SafetyVerdict,
    Z3Result,
)
from argus.orchestration import pipeline
from argus.orchestration.execution import handle_action
from argus.safety.gate import check

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures"


@pytest.fixture
def recorded_gate():
    snapshot = json.loads((FIXTURES / "m3/snapshot_hotel_reservation.json").read_text(encoding="utf-8"))
    return Mock(wraps=partial(check, snapshot=snapshot, settings=Settings(solver_timeout_s=30)))


@pytest.mark.parametrize("replicas,decision", [(2, GateDecision.APPROVE), (1, GateDecision.BLOCK)])
def test_real_gate_handoff_and_feedback(sample_batch, monkeypatch, recorded_gate, replicas, decision):
    command = f'  kubectl\t scale deployment "geo" --replicas={replicas} -n hotel-reservation  '
    action = ProposedAction(command=command, is_write=True, target_namespace="hotel-reservation")
    initial = DiagnosisResult(actions=[action])
    revised = DiagnosisResult(actions=[ProposedAction(command="must not run", is_write=True)])
    diagnose = Mock(side_effect=[initial, revised])
    executor = Mock(return_value=ExecutionResult(command=command, executed=False, output="recording stub"))
    monkeypatch.setattr(pipeline, "diagnose", diagnose)

    result = pipeline.run_once(sample_batch, gate=recorded_gate, executor=executor)

    recorded_gate.assert_called_once_with(action)
    assert recorded_gate.call_args.args[0].command.encode("utf-8") == command.encode("utf-8")
    verdict = result.verdicts[0]
    assert verdict.command.encode("utf-8") == command.encode("utf-8")
    assert verdict.decision is decision
    if decision is GateDecision.APPROVE:
        executor.assert_called_once_with(action)
        assert executor.call_args.args[0].command.encode("utf-8") == command.encode("utf-8")
        assert result.executions[0].command == command
        assert verdict.z3_result is Z3Result.UNSAT
        diagnose.assert_called_once_with(result.context)
        assert result.feedback_diagnosis is None
    else:
        executor.assert_not_called()
        assert result.executions == []
        assert verdict.z3_result is Z3Result.SAT
        assert verdict.counterexample["after"] == {"replicas": 1}
        assert diagnose.call_count == 2
        assert diagnose.call_args.kwargs["feedback"] == [verdict]
        assert diagnose.call_args.kwargs["feedback"][0] is verdict
        assert result.feedback_diagnosis == revised


def test_block_without_counterexample_reaches_m2(sample_batch, monkeypatch):
    action = ProposedAction(
        command="kubectl scale deploy geo --replicas=2 -n hotel-reservation", is_write=True
    )
    diagnose = Mock(side_effect=[DiagnosisResult(actions=[action]), DiagnosisResult()])
    monkeypatch.setattr(pipeline, "diagnose", diagnose)
    executor = Mock()

    result = pipeline.run_once(sample_batch, executor=executor)

    executor.assert_not_called()
    verdict = result.verdicts[0]
    assert verdict.decision is GateDecision.BLOCK
    assert verdict.counterexample is None
    assert "no cluster snapshot" in verdict.reason
    assert diagnose.call_args.kwargs["feedback"] == [verdict]


def test_multiline_command_is_preserved_and_blocked(recorded_gate):
    command = 'kubectl scale deployment "geo" --replicas=2 -n hotel-reservation\n'
    executor = Mock()
    result = handle_action(
        ProposedAction(command=command, is_write=True), gate=recorded_gate, executor=executor
    )
    assert recorded_gate.call_args.args[0].command == command
    assert result.verdict.command == command
    assert result.verdict.decision is GateDecision.BLOCK
    assert "multi-line" in result.verdict.reason
    executor.assert_not_called()


@pytest.mark.parametrize("failure", [TimeoutError("gate timed out"), RuntimeError("gate unavailable")])
def test_gate_exceptions_block_execution(failure):
    action = ProposedAction(command="kubectl delete pod geo-1 -n hotel-reservation", is_write=True)
    executor = Mock()
    result = handle_action(action, gate=Mock(side_effect=failure), executor=executor)
    assert result.verdict.decision is GateDecision.BLOCK
    assert result.verdict.command == action.command
    assert type(failure).__name__ in result.verdict.reason
    executor.assert_not_called()


@pytest.mark.parametrize(
    "verdict",
    [None, SafetyVerdict(command="different command", decision=GateDecision.APPROVE, reason="wrong action")],
)
def test_missing_or_mismatched_approval_blocks(verdict):
    executor = Mock()
    result = handle_action(
        ProposedAction(command="original command", is_write=True),
        gate=Mock(return_value=verdict),
        executor=executor,
    )
    assert result.verdict.decision is GateDecision.BLOCK
    assert result.verdict.command == "original command"
    executor.assert_not_called()


def test_reads_bypass_gate():
    action = ProposedAction(command="kubectl get pods -n hotel-reservation", is_write=False)
    gate = Mock(side_effect=AssertionError("read reached gate"))
    expected = ExecutionResult(command=action.command, executed=False, output="stub")
    executor = Mock(return_value=expected)
    result = handle_action(action, gate=gate, executor=executor)
    gate.assert_not_called()
    executor.assert_called_once_with(action)
    assert result.verdict is None
    assert result.execution is expected


def test_gate_cannot_rewrite_the_executed_proposal():
    action = ProposedAction(command="original command", is_write=True)

    def mutating_gate(proposal):
        proposal.command = "rewritten command"
        return SafetyVerdict(command=proposal.command, decision=GateDecision.APPROVE, reason="changed")

    executor = Mock()
    result = handle_action(action, gate=mutating_gate, executor=executor)
    assert action.command == "original command"
    assert result.verdict.decision is GateDecision.BLOCK
    executor.assert_not_called()
