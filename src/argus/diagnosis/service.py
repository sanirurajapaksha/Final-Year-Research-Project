"""M2 entry point: M1's SemanticContext in, ranked hypotheses and proposed actions out.

diagnose() is the only place M2's internal models are turned into the shared contracts:
ADAPT (context_adapter) -> loop (controller) -> convert (this file).
"""

from argus.contracts import (
    DiagnosisResult,
    GateDecision,
    Hypothesis,
    ProposedAction,
    SafetyVerdict,
    SemanticContext,
)
from argus.diagnosis.core.belief import H0
from argus.diagnosis.core.config import DiagnosisConfig
from argus.diagnosis.core.models import Evidence, HypothesisSpec
from argus.diagnosis.loop.context_adapter import adapt
from argus.diagnosis.loop.controller import Controller, LoopResult
from argus.diagnosis.ports.base import LLMClient, ReadExecutor

EVIDENCE_CHARS = 200  # how much of each read's output a hypothesis carries as evidence


def diagnose(
    context: SemanticContext,
    feedback: list[SafetyVerdict] | None = None,
    *,
    config: DiagnosisConfig | None = None,
    llm: LLMClient | None = None,
    reads: ReadExecutor | None = None,
) -> DiagnosisResult:
    """Rank root-cause hypotheses and propose the next actions.

    `feedback` carries M3's BLOCK verdicts (with counterexamples) from the previous round,
    so M2 never proposes a blocked command again.

    The keyword-only arguments are for tests and the demo. M4 calls diagnose(context) and
    diagnose(context, feedback=...), so with no LLM and no cluster the loop falls back to rules
    and neutral reads.
    """
    cfg = config or DiagnosisConfig()
    ctx = adapt(context, cfg.namespace)
    result = Controller(cfg, llm=llm, reads=reads).run(ctx)
    return to_result(result, cfg.namespace, blocked_commands(feedback))


def to_result(result: LoopResult, namespace: str, blocked: set[str]) -> DiagnosisResult:
    """Turn the loop's belief state into the contract: hypotheses best first, then actions."""
    ranked = [(h, p) for h, p in result.belief.ranked() if h != H0]
    hypotheses = [
        Hypothesis(
            root_cause=result.hypotheses[h].label(),
            probability=round(p, 4),
            evidence=_evidence_lines(h, result.evidence),
        )
        for h, p in ranked
    ]
    actions: list[ProposedAction] = []
    if ranked:
        top = result.hypotheses[ranked[0][0]]
        actions.append(_read_action(top, namespace))
        actions += propose_writes(top, namespace)
    kept = [a for a in actions if a.command not in blocked]
    return DiagnosisResult(hypotheses=hypotheses, actions=kept)


def propose_writes(top: HypothesisSpec, namespace: str) -> list[ProposedAction]:
    """Write actions that would fix the top hypothesis. None yet: added in the next task (step 3)."""
    return []


def blocked_commands(feedback: list[SafetyVerdict] | None) -> set[str]:
    """Commands M3 blocked last round. They are compared byte-exact, as M3 checked them."""
    blocked: set[str] = set()
    for verdict in feedback or []:
        if verdict.decision == GateDecision.BLOCK:
            blocked.add(verdict.command)
    return blocked


def _read_action(top: HypothesisSpec, namespace: str) -> ProposedAction:
    """The read that confirms the top hypothesis, so M4 can show or re-run it."""
    return ProposedAction(
        command=top.test,
        is_write=False,
        target_namespace=namespace,
        rationale=f"check {top.label()}: expect {top.expected}",
    )


def _evidence_lines(hyp_id: str, evidence: list[Evidence]) -> list[str]:
    """One line per read run for this hypothesis: E1: command -> start of the output."""
    lines: list[str] = []
    for e in evidence:
        if e.hyp_id != hyp_id:
            continue
        status = "ok" if e.ok else "failed"
        lines.append(f"{e.id} ({status}): {e.command} -> {e.output[:EVIDENCE_CHARS]}")
    return lines