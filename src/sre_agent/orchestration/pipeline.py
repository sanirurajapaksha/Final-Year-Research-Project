"""One pass through the whole system, in the order the team agreed.

    telemetry -> M4 (compress) -> M1 (context) -> M2 (diagnose) -> for each write: M3 (gate) -> M4 (execute)

This wiring is framework-agnostic on purpose: the orchestration framework (CrewAI or
LangGraph) isn't chosen yet. When it is, this function becomes the graph or crew, but the
rule stays: read actions run freely, and every write action passes M3 before it executes.
"""

from dataclasses import dataclass, field

from sre_agent.context.service import build_context
from sre_agent.contracts import (
    DiagnosisResult,
    ExecutionResult,
    GateDecision,
    SafetyVerdict,
    SemanticContext,
    TelemetryBatch,
)
from sre_agent.diagnosis.service import diagnose
from sre_agent.orchestration.service import compress, execute
from sre_agent.safety.gate import check


@dataclass
class PipelineResult:
    context: SemanticContext
    diagnosis: DiagnosisResult
    verdicts: list[SafetyVerdict] = field(default_factory=list)
    executions: list[ExecutionResult] = field(default_factory=list)


def run_once(batch: TelemetryBatch) -> PipelineResult:
    compressed = compress(batch)
    context = build_context(compressed)
    diagnosis = diagnose(context)
    result = PipelineResult(context=context, diagnosis=diagnosis)

    for action in diagnosis.actions:
        if not action.is_write:
            result.executions.append(execute(action))
            continue
        verdict = check(action)
        result.verdicts.append(verdict)
        if verdict.decision is GateDecision.APPROVE:
            result.executions.append(execute(action))
        # BLOCK verdicts go back to M2 as `feedback` in the next round (round loop not built yet).

    return result
