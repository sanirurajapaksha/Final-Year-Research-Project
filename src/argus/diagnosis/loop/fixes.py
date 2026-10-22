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

from argus.contracts import ProposedAction, SafetyVerdict
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


def scale_command(target: str, replicas: int, namespace: str) -> str:
    """Set the replica count (M3's parser reads exactly this form)."""
    return f"kubectl scale deployment {target} --replicas={replicas} -n {namespace}"


def stopgap_restart(top: HypothesisSpec, namespace: str) -> ProposedAction:
    """A restart offered when no command fixes `top`: it clears the bad state, a person fixes the cause."""
    return ProposedAction(
        command=restart_command(top.component, namespace),
        is_write=True,
        target_namespace=namespace,
        rationale=f"stopgap only: restart {top.component}; it does not fix {top.label()}, a person must",
    )


def scale_up_for_restart(
    top: HypothesisSpec, namespace: str, verdict: SafetyVerdict
) -> ProposedAction | None:
    """After M3 blocked the restart for leaving too few pods up: add replicas so the restart fits.

    Uses M3's counterexample only when every number in it came from the cluster, not from the solver
    (a missing fact is chosen by Z3 to break the rule, so it says nothing about the real deployment).
    """
    example = verdict.counterexample or {}
    before = example.get("before", {})
    if (
        "during" not in example
        or "min_available_during_restart" not in verdict.violated_invariants
        or example.get("missing_facts_chosen_by_solver")
    ):
        return None
    try:
        replicas, minimum = int(before["replicas"]), int(before["min_replicas"])
        down = int(before["max_unavailable"])
    except (KeyError, TypeError, ValueError):
        return None
    # Enough that `down` pods may go during the restart and `minimum` still stay up.
    target = max(replicas + 1, minimum + max(down, 1))
    return ProposedAction(
        command=scale_command(top.component, target, namespace),
        is_write=True,
        target_namespace=namespace,
        rationale=(
            f"scale {top.component} from {replicas} to {target} replicas so a rolling restart keeps "
            f"{minimum} available; then restart it ({top.label()})"
        ),
    )


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
