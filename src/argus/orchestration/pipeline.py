"""One pass through the whole system, in the order the team agreed.

    telemetry -> M4 (compress) -> M1 (context) -> M2 (diagnose) -> for each write: M3 (gate) -> M4 (execute)

This wiring is framework-agnostic on purpose: the orchestration framework (CrewAI or
LangGraph) isn't chosen yet. When it is, this function becomes the graph or crew, but the
rule stays: read actions run freely, and every write action passes M3 before it executes.
"""

from dataclasses import dataclass, field

from argus.context.service import build_context
from argus.contracts import (
    DiagnosisResult,
    ExecutionResult,
    GateDecision,
    SafetyVerdict,
    SemanticContext,
    TelemetryBatch,
)
from argus.diagnosis.service import diagnose
from argus.orchestration.execution import Executor, Gate, handle_action
from argus.orchestration.service import compress


@dataclass
class PipelineResult:
    context: SemanticContext
    diagnosis: DiagnosisResult
    verdicts: list[SafetyVerdict] = field(default_factory=list)
    executions: list[ExecutionResult] = field(default_factory=list)
    feedback_diagnosis: DiagnosisResult | None = None


def run_once(
    batch: TelemetryBatch, *, gate: Gate | None = None, executor: Executor | None = None
) -> PipelineResult:
    """Process one action batch and hand any blocked verdicts back to M2 once.

    Retain M2's feedback response for the next round without executing its actions.
    Automatic retries and incident-round limits belong to the later routing work.
    """
    compressed = compress(batch)
    context = build_context(compressed)
    diagnosis = diagnose(context)
    result = PipelineResult(context=context, diagnosis=diagnosis)

    for action in diagnosis.actions:
        handled = handle_action(action, gate=gate, executor=executor)
        if handled.verdict is not None:
            result.verdicts.append(handled.verdict)
        if handled.execution is not None:
            result.executions.append(handled.execution)

    blocked = [verdict for verdict in result.verdicts if verdict.decision is GateDecision.BLOCK]
    if blocked:
        result.feedback_diagnosis = diagnose(context, feedback=blocked)

    return result
