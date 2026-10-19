"""FIX step: the write action that would repair the top hypothesis, in a form M3 can check.

Rule-based, one fix per fault layer. Every command is one plain kubectl call with -n always
given and no shell syntax (no pipes, &&, ;, $() or backticks), because M3 blocks anything else.
M2 only proposes: M4 sends each write to M3, and nothing here runs a command.
"""

import json
import re

from argus.contracts import ProposedAction
from argus.diagnosis.core.models import DiagContext, HypothesisSpec

# DEMO KNOWLEDGE, not discovered: the address each *_ADDR variable should hold in the
# scenario_01 cluster (Online Boutique layout, namespace default). A real run would read it
# from the cluster's Service list instead.
KNOWN_ADDRESSES = {"CART_ADDR": "redis-cart:6379"}

# An address variable named in M1's evidence, e.g. "CART_ADDR environment variable not set".
ADDRESS_VAR = re.compile(r"\b([A-Z][A-Z0-9_]*_ADDR)\b")


def propose_fix(top: HypothesisSpec, ctx: DiagContext) -> ProposedAction | None:
    """The write that fixes `top`, or None when M2 doesn't know a safe one."""
    if top.layer == "app-config":
        return _set_address(top, ctx)
    if top.layer in ("k8s-network", "resources"):
        return _restart(top, ctx.namespace)
    return None


def address_var(component: str, symptoms: list[str]) -> str | None:
    """The first *_ADDR variable named in this component's symptom lines ("cart: ...")."""
    for line in symptoms:
        if not line.startswith(f"{component}:"):
            continue
        match = ADDRESS_VAR.search(line)
        if match:
            return match.group(1)
    return None


def _set_address(top: HypothesisSpec, ctx: DiagContext) -> ProposedAction | None:
    """Patch the missing address env var onto the component's container (spec.template only)."""
    var = address_var(top.component, ctx.symptoms)
    if var is None or var not in KNOWN_ADDRESSES:
        return None  # we'd have to guess the name or the value: propose nothing instead
    container = {"name": top.component, "env": [{"name": var, "value": KNOWN_ADDRESSES[var]}]}
    patch = {"spec": {"template": {"spec": {"containers": [container]}}}}
    body = json.dumps(patch, separators=(",", ":"))
    return ProposedAction(
        command=f"kubectl patch deployment {top.component} -n {ctx.namespace} -p '{body}'",
        is_write=True,
        target_namespace=ctx.namespace,
        rationale=f"set {var} on the {top.component} container ({top.label()})",
    )


def _restart(top: HypothesisSpec, namespace: str) -> ProposedAction:
    """Rolling restart: new pods come up before old ones go, so the service stays available."""
    return ProposedAction(
        command=f"kubectl rollout restart deployment/{top.component} -n {namespace}",
        is_write=True,
        target_namespace=namespace,
        rationale=f"restart {top.component} ({top.label()})",
    )