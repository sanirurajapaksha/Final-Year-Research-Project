"""SCORE step without an LLM: read one piece of evidence with fixed rules, one rule per fault layer.

The LLM scorer is the main path; this is the no-LLM fallback, like RuleGenerator for DRAFT.
A rule only judges the hypotheses whose own test produced the evidence; every other
hypothesis stays neutral, and so does anything a rule can't read.
"""

import json
import re

from argus.diagnosis.core.models import DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.loop.fixes import KNOWN_ADDRESSES, address_var

# `kubectl describe pods`: why the last container run ended, e.g. "Last State: Terminated / Reason: Error".
LAST_REASON = re.compile(r"Last State:\s+Terminated\s*\n\s+Reason:\s+\w+")
LAST_EXIT_137 = re.compile(r"Exit Code:\s+137\b")  # SIGKILL: what the kernel's OOM killer sends


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
    if hyp.layer == "storage":
        return _disk_full(output)
    return "neutral"


def _disk_full(logs: str) -> str:
    """`kubectl logs --previous`: the crashed container's last lines. ENOSPC supports a full volume;
    other lines only weakly refute it, since the tail may have cut the write error off."""
    lowered = logs.lower()
    if "no space left on device" in lowered or "enospc" in lowered:
        return "strong-support"
    if logs.strip():
        return "weak-refute"
    return "neutral"


def _address_set(component: str, deployment_json: str, ctx: DiagContext) -> str:
    """The *_ADDR variable M1's evidence names, checked in the component's own container.

    Missing, empty or set to a wrong address supports the fault ("missing or wrong"); set to the
    known address refutes it. Whatever M2 can't establish stays neutral.
    """
    var = address_var(component, ctx.symptoms)
    if var is None:
        return "neutral"  # no variable named in the evidence, so nothing to look for
    env = _container_env(component, deployment_json)
    if env is None:
        return "neutral"  # not a deployment M2 can read, or no container with that name
    if var not in env or env[var] == "":
        return "strong-support"
    if env[var] is None:
        return "neutral"  # the value comes from a Secret or ConfigMap, which this read doesn't show
    expected = KNOWN_ADDRESSES.get(var)
    if expected is None:
        return "neutral"  # set, but M2 doesn't know what the right address is
    if env[var] == expected:
        return "strong-refute"
    return "strong-support"  # set, but to the wrong address


def _container_env(component: str, deployment_json: str) -> dict[str, str | None] | None:
    """`kubectl get deployment -o json`: the env of the container named `component`, name -> value.

    A variable set with valueFrom has no plain value, so it maps to None. Returns None when the
    output isn't a deployment or has no container with that name.
    """
    try:
        deployment = json.loads(deployment_json)
        containers = deployment["spec"]["template"]["spec"]["containers"]
        for container in containers:
            if container.get("name") != component:
                continue
            env: dict[str, str | None] = {}
            for item in container.get("env", []):
                env[item["name"]] = item.get("value")
            return env
    except (ValueError, KeyError, TypeError, AttributeError):
        return None  # not JSON, or not shaped like a deployment
    return None


def _endpoints_ready(component: str, endpoints: str) -> str:
    """`kubectl get endpoints`: in the row whose NAME is the component, "<none>" means no ready pods.

    Only that row counts: matching the whole name means a service "ad" doesn't match "adservice".
    """
    for line in endpoints.splitlines():
        columns = line.split()
        if len(columns) < 2 or columns[0] != component:
            continue  # the header, another service's row, or a line that isn't a row
        if columns[1] == "<none>":
            return "strong-support"
        return "strong-refute"  # the Service's row lists at least one address
    return "neutral"


def _pods_healthy(describe: str) -> str:
    """`kubectl describe pods`: an OOMKill or crash loop supports the fault, Running refutes it.

    Except a crash loop whose last run ended for another named reason and not with exit code 137
    ("Reason: Error", exit code 14): a memory limit kills with OOMKilled / 137 and a CPU limit only
    throttles, so the container stopped itself, as a full disk or a bad config makes it do.
    """
    if "OOMKilled" in describe:
        return "strong-support"
    if "CrashLoopBackOff" in describe:
        killed = LAST_EXIT_137.search(describe)
        return "strong-refute" if LAST_REASON.search(describe) and not killed else "strong-support"
    if "Running" in describe:
        return "strong-refute"
    return "neutral"
