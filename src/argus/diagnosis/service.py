"""M2 entry point.

STUB: replace the body. Keep the signature until contract v1 changes it.
"""

from argus.contracts import (
    DiagnosisResult,
    Hypothesis,
    ProposedAction,
    SafetyVerdict,
    SemanticContext,
)


def diagnose(context: SemanticContext, feedback: list[SafetyVerdict] | None = None) -> DiagnosisResult:
    """Rank root-cause hypotheses and propose the next actions.

    `feedback` carries M3's BLOCK verdicts (with counterexamples) from the previous round,
    so M2 can propose a different action instead of repeating a blocked one.

    The stub returns one read and one write action so the whole pipeline can be exercised.
    """
    return DiagnosisResult(
        hypotheses=[Hypothesis(root_cause="stub: M2 not implemented yet", probability=1.0)],
        actions=[
            ProposedAction(command="kubectl get pods -n demo", is_write=False, target_namespace="demo"),
            ProposedAction(
                command="kubectl scale deployment demo --replicas=0 -n demo",
                is_write=True,
                target_namespace="demo",
            ),
        ],
    )
