"""DRAFT step: rival hypotheses for the loop to test.

RuleGenerator is the no-LLM fallback: it pairs the top candidates with a small table of common
faults. `validate` holds the rules every generator must obey, so LLMGenerator reuses it.
"""

import re

from argus.diagnosis.core.models import DiagContext, HypothesisSpec
from argus.diagnosis.core.readonly import is_read_only
from argus.diagnosis.loop.clues import NONE, layer_score

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
    # Before resources: a full disk also crash-loops the pod, so on a tie the deeper cause is tested first.
    # Only drafted on a clue (CLUE_ONLY): a full disk always logs ENOSPC, so without one it isn't guessed.
    (
        "storage",
        "data volume full (no space left on device)",
        "kubectl logs deployment/{svc} -n {ns} --previous --tail=50",
        "No space left on device (ENOSPC) in the crashed container's last log lines",
    ),
    (
        "resources",
        "container OOMKilled or crash-looping",
        "kubectl describe pods -n {ns} -l app={svc}",
        "Last State: Terminated (OOMKilled) or CrashLoopBackOff",
    ),
]
CLUE_ONLY = {"storage"}  # layers drafted only when M1's evidence already points at them


def validate(
    specs: list[HypothesisSpec],
    ctx: DiagContext,
    refuted: set[tuple[str, str]],
    k: int,
    next_id: int = 1,
    per_component: int | None = None,
) -> list[HypothesisSpec]:
    """Keep at most k specs that name a known candidate, use a read-only test and aren't refuted.
    Ids are assigned here, never taken from the source.

    With `per_component`, at most that many specs per component come first, so a round tests rival
    components (when all k sit on one component they share one graph weight, which then cancels out
    of the prior). Held-back specs only fill a round that would otherwise have fewer than k.
    None keeps the specs' own order: usually every guess lands on the top candidate.

    `refuted` holds (component, fault) and (component, layer) pairs already tried. Matching on the
    layer too stops a reworded repeat: the LLM's "CART_ADDR env var missing" and the rules' "missing
    or wrong dependency address env var" are the same idea, and their read was already judged.

    A component is known when it is a candidate or is named, as a whole word, in M1's symptom lines:
    "failed to connect to redis" makes `redis` testable even when M1 never listed it as a service.
    """
    known = {c.service for c in ctx.candidates} | _named_in(ctx.symptoms, {s.component for s in specs})
    seen = set(refuted)
    usable: list[HypothesisSpec] = []
    for spec in specs:
        keys = {(spec.component, spec.fault), (spec.component, spec.layer)}
        if spec.component not in known or not is_read_only(spec.test) or keys & seen:
            continue
        seen |= keys
        usable.append(spec)

    if per_component is not None:
        first: list[HypothesisSpec] = []
        held: list[HypothesisSpec] = []
        count: dict[str, int] = {}
        for spec in usable:
            count[spec.component] = count.get(spec.component, 0) + 1
            (first if count[spec.component] <= per_component else held).append(spec)
        usable = first + held
    return [spec.model_copy(update={"id": f"H{next_id + i}"}) for i, spec in enumerate(usable[:k])]


SERVICE_NAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?")  # a Kubernetes object name


def _named_in(symptoms: list[str], names: set[str]) -> set[str]:
    """The names that appear as a whole word in the symptom lines (and look like Kubernetes names)."""
    text = "\n".join(symptoms)
    return {
        n
        for n in names
        if SERVICE_NAME.fullmatch(n) and re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text)
    }


class RuleGenerator:
    """Signature table x candidates, highest graph prior first. Deterministic.

    With `use_clues` (the default) each guess's confidence comes from clues.layer_score, and within a
    candidate the layers the evidence points at come first. Without it every guess gets 0.5, as in
    the Almanac's plain rule fallback.
    """

    def __init__(self, use_clues: bool = True, per_component: int | None = None) -> None:
        self.use_clues = use_clues
        self.per_component = per_component  # see validate(): spread a round over rival components

    def draft(
        self,
        ctx: DiagContext,
        k: int,
        refuted: set[tuple[str, str]] = frozenset(),
        next_id: int = 1,
    ) -> list[HypothesisSpec]:
        specs: list[HypothesisSpec] = []
        for c in ctx.candidates:
            own = [
                HypothesisSpec(
                    component=c.service,
                    layer=layer,
                    fault=fault,
                    test=test.format(svc=c.service, ns=ctx.namespace),
                    expected=expected,
                    confidence=layer_score(c.service, layer, ctx) if self.use_clues else 0.5,
                )
                for layer, fault, test, expected in SIGNATURES
                if layer not in CLUE_ONLY or (self.use_clues and layer_score(c.service, layer, ctx) > NONE)
            ]
            specs += sorted(own, key=lambda h: -h.confidence)  # stable: ties keep the table's order
        return validate(specs, ctx, refuted, k, next_id, self.per_component)
