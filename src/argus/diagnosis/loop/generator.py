"""DRAFT step: rival hypotheses for the loop to test.

RuleGenerator is the no-LLM fallback: it pairs the top candidates with a small table of common
faults. `validate` holds the rules every generator must obey, so LLMGenerator (step 7) reuses it.
"""

from argus.diagnosis.core.models import DiagContext, HypothesisSpec
from argus.diagnosis.core.readonly import is_read_only

# (layer, fault, test template, what the test shows if the fault is real)
SIGNATURES = [
    (
        "app-config",
        "missing or wrong dependency address env var",
        "kubectl get deployment {svc} -n {ns} -o json",
        "env var for a callee is absent or points nowhere",
    ),
    (
        "k8s-network",
        "Service selects no ready pods",
        "kubectl get endpoints {svc} -n {ns}",
        "no ready addresses",
    ),
    (
        "resources",
        "container OOMKilled or crash-looping",
        "kubectl describe pods -n {ns} -l app={svc}",
        "Last State: Terminated (OOMKilled) or CrashLoopBackOff",
    ),
]


def validate(
    specs: list[HypothesisSpec],
    ctx: DiagContext,
    refuted: set[tuple[str, str]],
    k: int,
    next_id: int = 1,
) -> list[HypothesisSpec]:
    """Keep at most k specs that name a known candidate, use a read-only test and aren't refuted.
    Ids are assigned here, never taken from the source."""
    known = {c.service for c in ctx.candidates}
    seen = set(refuted)
    kept: list[HypothesisSpec] = []
    for spec in specs:
        key = (spec.component, spec.fault)
        if spec.component not in known or not is_read_only(spec.test) or key in seen:
            continue
        seen.add(key)
        kept.append(spec.model_copy(update={"id": f"H{next_id + len(kept)}"}))
        if len(kept) == k:
            break
    return kept


class RuleGenerator:
    """Signature table x candidates, highest graph prior first. Deterministic."""

    def draft(
        self,
        ctx: DiagContext,
        k: int,
        refuted: set[tuple[str, str]] = frozenset(),
        next_id: int = 1,
    ) -> list[HypothesisSpec]:
        specs = [
            HypothesisSpec(
                component=c.service,
                layer=layer,
                fault=fault,
                test=test.format(svc=c.service, ns=ctx.namespace),
                expected=expected,
            )
            for c in ctx.candidates
            for layer, fault, test, expected in SIGNATURES
        ]
        return validate(specs, ctx, refuted, k, next_id)
