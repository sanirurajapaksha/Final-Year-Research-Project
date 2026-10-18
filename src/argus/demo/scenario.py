"""SIMULATED M2 for the demo. This is not M2's diagnosis: Kaveen's diagnose() will replace it.

Scenario: M1's scenario_01, modelled on Stratus's example. The cart service is missing its
CART_ADDR environment variable, so it can't reach redis-cart and returns errors.

Round 1 proposes a risky restart that M3 should block. After M3's feedback, it proposes the
real fix as a patch, which M3 checks through its LLM Formulation Agent.
"""

from argus.contracts import DiagnosisResult, Hypothesis, ProposedAction, SafetyVerdict, SemanticContext

NAMESPACE = "default"
READ_PODS = "kubectl get pods -n default"
RISKY_RESTART = "kubectl scale deployment cart --replicas=0 -n default"
FIX = (
    "kubectl patch deployment cart -n default -p "
    '\'{"spec":{"template":{"spec":{"containers":[{"name":"cart","env":'
    '[{"name":"CART_ADDR","value":"redis-cart:6379"}]}]}}}}\''
)
MISSING_ADDRESS = "cart can't reach redis-cart: CART_ADDR is missing"


def simulated_diagnose(
    context: SemanticContext, feedback: list[SafetyVerdict] | None = None
) -> DiagnosisResult:
    """Called like M2's diagnose(): first without feedback, then with M3's BLOCK verdicts."""
    if not feedback:
        return DiagnosisResult(
            hypotheses=[
                Hypothesis(
                    root_cause=MISSING_ADDRESS, probability=0.6, evidence=["cart errors flagged by M1"]
                ),
                Hypothesis(root_cause="the cart pod is stuck and needs a restart", probability=0.4),
            ],
            actions=[
                ProposedAction(command=READ_PODS, is_write=False, target_namespace=NAMESPACE),
                ProposedAction(
                    command=RISKY_RESTART,
                    is_write=True,
                    target_namespace=NAMESPACE,
                    rationale="restart cart by scaling it to zero",
                ),
            ],
        )

    # M3 blocked the restart: drop that idea and propose the actual fix.
    return DiagnosisResult(
        hypotheses=[
            Hypothesis(root_cause=MISSING_ADDRESS, probability=0.85, evidence=[f"M3: {feedback[0].reason}"]),
        ],
        actions=[
            ProposedAction(
                command=FIX,
                is_write=True,
                target_namespace=NAMESPACE,
                rationale="set CART_ADDR on the cart container",
            ),
        ],
    )
