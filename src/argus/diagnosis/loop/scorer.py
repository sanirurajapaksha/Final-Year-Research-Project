"""SCORE step without an LLM: read one piece of evidence with fixed rules, one rule per fault layer.

The LLM scorer is the main path; this is the no-LLM fallback, like RuleGenerator for DRAFT.
A rule only judges the hypotheses whose own test produced the evidence; every other
hypothesis stays neutral, and so does anything a rule can't read.
"""

from argus.diagnosis.core.models import DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.loop.fixes import address_var


class RuleScorer:
    """Deterministic verdicts from the read output: the same evidence always gives the same answer."""

    def score(
        self, evidence: Evidence, hypotheses: dict[str, HypothesisSpec], ctx: DiagContext
    ) -> dict[str, str]:
        verdicts: dict[str, str] = {}
        for hyp_id, hyp in hypotheses.items():
            if hyp.test != evidence.command:
                continue  # this read wasn't run to test this hypothesis
            verdict = _verdict(hyp, evidence.output, ctx)
            if verdict != "neutral":
                verdicts[hyp_id] = verdict
        return verdicts


def _verdict(hyp: HypothesisSpec, output: str, ctx: DiagContext) -> str:
    if hyp.layer == "app-config":
        return _address_set(hyp.component, output, ctx)
    if hyp.layer == "k8s-network":
        return _endpoints_ready(hyp.component, output)
    if hyp.layer == "resources":
        return _pods_healthy(output)
    return "neutral"


def _address_set(component: str, deployment_yaml: str, ctx: DiagContext) -> str:
    """The *_ADDR variable M1's evidence names: missing from the deployment supports the fault."""
    var = address_var(component, ctx.symptoms)
    if var is None:
        return "neutral"  # no variable named in the evidence, so nothing to look for
    if var in deployment_yaml:
        return "strong-refute"
    return "strong-support"


def _endpoints_ready(component: str, endpoints: str) -> str:
    """`kubectl get endpoints`: "<none>" means the Service selects no ready pods."""
    if "<none>" in endpoints:
        return "strong-support"
    if component in endpoints:
        return "strong-refute"  # the Service's row lists at least one address
    return "neutral"


def _pods_healthy(describe: str) -> str:
    """`kubectl describe pods`: an OOMKill or crash loop supports the fault, Running refutes it."""
    if "OOMKilled" in describe or "CrashLoopBackOff" in describe:
        return "strong-support"
    if "Running" in describe:
        return "strong-refute"
    return "neutral"
