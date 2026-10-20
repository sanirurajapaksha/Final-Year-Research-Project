"""CLUES: how strongly M1's evidence already points at each fault layer of a service (no LLM).

RuleGenerator uses this as the hypothesis confidence c(h), so rule mode stops giving every layer the
same 0.5. It looks at the service's own symptom lines ("cart: log_error (...)") and its pod status.

Only the strongest match per layer counts, never how many times it matches: a misconfigured pod can
log the same line 500 times, and a gateway logs an error for every request that fails below it, so
counting would reward repetition and victims rather than causes.
The score is capped between 0.1 and 0.9, so log text alone can never decide: a read still has to agree.
"""

from argus.diagnosis.core.models import DiagContext

STRONG = 0.8
WEAK = 0.4
NONE = 0.2
LOWEST = 0.1  # e.g. resources when the pod is plainly running

# layer -> (strong phrases, weak phrases), matched lower-case.
CLUES: dict[str, tuple[list[str], list[str]]] = {
    "app-config": (
        ["not set", "environment variable", "missing env", "invalid config", "_addr"],
        ["config", "env"],
    ),
    "k8s-network": (
        ["no endpoints", "connection refused", "no such host", "no route to host"],
        ["unavailable", "failed to connect", "timeout", "timed out", "deadline exceeded"],
    ),
    "resources": (
        ["oomkilled", "crashloopbackoff", "out of memory"],
        ["restart", "evicted", "memory"],
    ),
}
HEALTHY = {"running", "available"}


def layer_score(service: str, layer: str, ctx: DiagContext) -> float:
    """c(h) for a hypothesis about `layer` in `service`, from 0.1 to 0.9. Unknown layer: neutral 0.5."""
    if layer not in CLUES:
        return 0.5
    strong, weak = CLUES[layer]
    status = ctx.node_status.get(service, "").lower()
    text = " ".join([*_own_lines(service, ctx.symptoms), status]).lower()
    if any(p in text for p in strong):
        return STRONG
    if layer == "resources" and status in HEALTHY:
        return LOWEST  # the pod is up and nothing says otherwise
    if any(p in text for p in weak):
        return WEAK
    return NONE


def _own_lines(service: str, symptoms: list[str]) -> list[str]:
    """The symptom lines about this service, without the "service:" prefix so its name can't match."""
    prefix = f"{service}:"
    return [line[len(prefix) :] for line in symptoms if line.startswith(prefix)]
