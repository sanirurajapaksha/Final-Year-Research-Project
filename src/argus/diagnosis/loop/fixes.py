"""FIX step: the write action that would repair the top hypothesis, in a form M3 can check.

Rule-based, one fix per fault layer: the fallback when no LLM is available (llm_fixer.py is the
LLM path). Every command is one plain kubectl call with -n always given and no shell syntax (no pipes,
&&, ;, $() or backticks), because M3 blocks anything else. M3 accepts `kubectl patch deployment`
(its formulation agent) and `kubectl rollout restart`; it has no `kubectl set env`, so an env var is
set with a patch. patch_env_command and restart_command build every fix, rules or LLM, so the same
fix is always the same byte-exact string.
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


def patch_env_command(target: str, var: str, value: str, namespace: str) -> str:
    """Set one env var on the deployment's container of the same name (changes spec.template only)."""
    container = {"name": target, "env": [{"name": var, "value": value}]}
    patch = {"spec": {"template": {"spec": {"containers": [container]}}}}
    body = json.dumps(patch, separators=(",", ":"))
    return f"kubectl patch deployment {target} -n {namespace} -p '{body}'"


def restart_command(target: str, namespace: str) -> str:
    """Rolling restart: new pods come up before old ones go, so the service stays available."""
    return f"kubectl rollout restart deployment/{target} -n {namespace}"


def _set_address(top: HypothesisSpec, ctx: DiagContext) -> ProposedAction | None:
    """Patch the missing address env var onto the component's container (spec.template only)."""
    var = address_var(top.component, ctx.symptoms)
    if var is None or var not in KNOWN_ADDRESSES:
        return None  # we'd have to guess the name or the value: propose nothing instead
    return ProposedAction(
        command=patch_env_command(top.component, var, KNOWN_ADDRESSES[var], ctx.namespace),
        is_write=True,
        target_namespace=ctx.namespace,
        rationale=f"set {var} on the {top.component} container ({top.label()})",
    )


def _restart(top: HypothesisSpec, namespace: str) -> ProposedAction:
    return ProposedAction(
        command=restart_command(top.component, namespace),
        is_write=True,
        target_namespace=namespace,
        rationale=f"restart {top.component} ({top.label()})",
    )
