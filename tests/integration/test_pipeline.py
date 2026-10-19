from argus.contracts import DiagnosisResult, GateDecision, ProposedAction
from argus.orchestration.pipeline import run_once


def test_every_write_gets_a_verdict(sample_batch):
    result = run_once(sample_batch)
    writes = [a.command for a in result.diagnosis.actions if a.is_write]
    assert sorted(v.command for v in result.verdicts) == sorted(writes)


def test_no_write_reaches_execution_without_approval(sample_batch):
    result = run_once(sample_batch)
    writes = {a.command for a in result.diagnosis.actions if a.is_write}
    approved = {v.command for v in result.verdicts if v.decision is GateDecision.APPROVE}
    executed_writes = {e.command for e in result.executions if e.command in writes}
    assert executed_writes <= approved


def test_a_diagnoser_can_replace_m2(sample_batch):
    # The demo passes a labelled simulation of M2 this way until M2's diagnose() is ready.
    calls = []

    def simulated(context, feedback=None):
        calls.append(feedback)
        write = ProposedAction(command="kubectl scale deployment geo --replicas=2 -n x", is_write=True)
        return DiagnosisResult(actions=[write])

    result = run_once(sample_batch, diagnoser=simulated)

    assert result.diagnosis.actions[0].command == "kubectl scale deployment geo --replicas=2 -n x"
    assert calls[0] is None
    # M3 has no facts for namespace "x", so the write is blocked and the simulation gets the feedback.
    assert calls[1] == result.verdicts
