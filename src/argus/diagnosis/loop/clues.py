"""CLUES: how strongly M1's evidence already points at each fault layer of a service (no LLM).

RuleGenerator uses this as the hypothesis confidence c(h), so rule mode stops giving every layer the
same 0.5. It looks at the service's own symptom lines ("cart: log_error (...)") and its pod status.

Only the strongest match per layer counts, never how many times it matches: a misconfigured pod can
log the same line 500 times, and a gateway logs an error for every request that fails below it, so
counting would reward repetition and victims rather than causes.
The score is capped between 0.1 and 0.9, so log text alone can never decide: a read still has to agree.

Phrases match whole words only ("env" is not in "envoy"), and an address variable must look like one:
an upper-case env var name ending in _ADDR, _HOST or _URL (CART_ADDR), not an access-log field such
as remote_addr or peer_addr. For the phrases, "_" separates words, so M1's own signal names match
(memory_utilization -> "memory", restart_count -> "restart"), and a word may take a plain ending
(-s, -es, -ed, -ing), so "restart" also matches "restarted" and "timeout" matches "timeouts".
A Running pod lowers resources only when nothing in the lines points at resources at all: a memory
spike or six restarts on a running pod is still a weak clue.

Caveat: the phrase table was written with scenario_01's CART_ADDR line in view, so how well rule mode
does on scenario_01 mostly shows that the table fits it. Results on other cases (the fixtures in
data/fixtures/m2/contexts/ and, later, SREGym) are the evidence; scenario_01 alone is not.
"""

import re

from argus.diagnosis.core.models import DiagContext

STRONG = 0.8
WEAK = 0.4
NONE = 0.2
LOWEST = 0.1  # e.g. resources when the pod is plainly running

# layer -> (strong phrases, weak phrases), matched lower-case as whole words.
CLUES: dict[str, tuple[list[str], list[str]]] = {
    "app-config": (
        ["not set", "environment variable", "missing env", "invalid config"],
        ["config", "env"],
    ),
    "k8s-network": (
        ["no endpoints", "connection refused", "no such host", "no route to host"],
        ["unavailable", "failed to connect", "timeout", "timed out", "deadline exceeded"],
    ),
    "storage": (
        ["no space left on device", "enospc", "disk full", "disk pressure"],
        ["filesystem", "disk", "volume", "pvc"],
    ),
    "resources": (
        ["oomkilled", "crashloopbackoff", "out of memory"],
        ["restart", "evicted", "memory", "cpu"],
    ),
}
# A strong app-config clue on the original (not lower-cased) text: an env var naming an address.
ADDRESS_VAR = re.compile(r"(?<![\w-])[A-Z][A-Z0-9_]*_(?:ADDR|HOST|URL)(?![\w-])")
HEALTHY = {"running", "available"}


def layer_score(service: str, layer: str, ctx: DiagContext) -> float:
    """c(h) for a hypothesis about `layer` in `service`, from 0.1 to 0.9. Unknown layer: neutral 0.5."""
    if layer not in CLUES:
        return 0.5
    strong, weak = CLUES[layer]
    status = ctx.node_status.get(service, "")
    text = " ".join([*_own_lines(service, ctx.symptoms), status])
    words = text.lower().replace("_", " ")  # M1's signal names use _ between words
    if any(_has(p, words) for p in strong) or (layer == "app-config" and ADDRESS_VAR.search(text)):
        return STRONG
    if any(_has(p, words) for p in weak):
        return WEAK  # checked before the pod status: a weak clue beats "the pod is up"
    if layer == "resources" and status.lower() in HEALTHY:
        return LOWEST  # the pod is up and nothing says otherwise
    return NONE


def _has(phrase: str, text: str) -> bool:
    """`phrase` occurs in `text` as whole words, allowing a plain ending: "restart" matches "restarted"
    and "restarts", "timeout" matches "timeouts"; "env" still doesn't match "envoy"."""
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?:s|es|ed|ing)?(?![\w-])", text) is not None


def _own_lines(service: str, symptoms: list[str]) -> list[str]:
    """The symptom lines about this service, without the "service:" prefix so its name can't match."""
    prefix = f"{service}:"
    return [line[len(prefix) :] for line in symptoms if line.startswith(prefix)]
