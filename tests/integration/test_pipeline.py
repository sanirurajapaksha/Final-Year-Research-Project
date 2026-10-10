from sre_agent.contracts import GateDecision
from sre_agent.orchestration.pipeline import run_once


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
