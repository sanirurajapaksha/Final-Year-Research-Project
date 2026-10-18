"""Step 1: Constraint Extractor (no LLM).

Builds M3's snapshot of one namespace (the format described in snapshot.py) from read-only
kubectl output:

    kubectl get deployments -n NS -o json    replicas, maxUnavailable, maxSurge
    kubectl get pdb -n NS -o json            minimum replicas (PodDisruptionBudget minAvailable)
    kubectl get pods -n NS -o json           which PVCs a pod uses
    kubectl get pvc -n NS -o json            the PVCs

Each command goes through a `run(command) -> output` function, so the same code works with:
    saved kubectl output (no cluster yet)      saved_output(folder)
    kubectl on a live cluster                  live_kubectl(context)
    SREGym's Kubernetes MCP server (later)     it wraps the kubectl CLI, so it takes the same commands

Read-only: the extractor only ever builds `kubectl get` commands, and every runner refuses
anything else. The namespace comes from the proposed command, so it must be a valid namespace
name before it goes into a read command (otherwise text like `ns --server=...` adds flags).
"""

import json
import math
import re
import shlex
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

Runner = Callable[[str], str]

# A namespace name is a DNS-1123 label: at most 63 characters, lowercase letters, digits and '-',
# starting and ending with a letter or digit (Kubernetes docs, "Object Names and IDs").
NAMESPACE_NAME = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")


def extract(namespace: str, run: Runner) -> dict[str, Any]:
    """Return M3's snapshot of one namespace."""
    if len(namespace) > 63 or NAMESPACE_NAME.fullmatch(namespace) is None:
        raise ValueError(f"not a valid namespace name: {namespace!r}")

    deployments = _get(run, "deployments", namespace)
    pdbs = _get(run, "pdb", namespace)
    pods = _get(run, "pods", namespace)
    pvcs = _get(run, "pvc", namespace)

    snapshot = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deployments": [],
        "pvcs": [],
    }
    for item in deployments:
        snapshot["deployments"].append(_deployment_facts(item, pdbs))

    claims_in_use = _claims_in_use(pods)
    for item in pvcs:
        name = item["metadata"]["name"]
        snapshot["pvcs"].append({"namespace": namespace, "name": name, "in_use": name in claims_in_use})
    return snapshot


def is_read_only(command: str) -> bool:
    """True only for `kubectl get ...`."""
    tokens = shlex.split(command)
    return len(tokens) >= 2 and tokens[0] == "kubectl" and tokens[1] == "get"


def _get(run: Runner, resource: str, namespace: str) -> list[dict[str, Any]]:
    command = f"kubectl get {resource} -n {namespace} -o json"
    return json.loads(run(command))["items"]


def _deployment_facts(item: dict[str, Any], pdbs: list[dict[str, Any]]) -> dict[str, Any]:
    spec = item["spec"]
    strategy = spec.get("strategy", {})
    if strategy.get("type") == "Recreate":
        # Recreate stops every pod before it starts the new ones.
        max_unavailable = "100%"
        max_surge = 0
    else:
        rolling = strategy.get("rollingUpdate", {})
        max_unavailable = rolling.get("maxUnavailable")
        max_surge = rolling.get("maxSurge")
    return {
        "namespace": item["metadata"]["namespace"],
        "name": item["metadata"]["name"],
        "replicas": spec.get("replicas"),
        "min_replicas": _min_available(item, pdbs),
        "max_unavailable": max_unavailable,
        "max_surge": max_surge,
    }


def _min_available(deployment: dict[str, Any], pdbs: list[dict[str, Any]]) -> int | None:
    """Minimum replicas, from the one PodDisruptionBudget that selects this deployment's pods.

    None (unknown, so M3 fails safe) when no PDB or more than one selects them, when a PDB's
    selector can't be read (it might select them), or when the PDB sets maxUnavailable instead
    of minAvailable (F1 reads only minAvailable).
    """
    labels = deployment["spec"]["template"]["metadata"].get("labels", {})
    matching = []
    for pdb in pdbs:
        selects = _selects(pdb["spec"].get("selector"), labels)
        if selects is None:
            return None
        if selects:
            matching.append(pdb)
    if len(matching) != 1:
        return None

    value = matching[0]["spec"].get("minAvailable")
    if isinstance(value, str) and value.endswith("%"):
        # A percentage of the pods, rounded up (Kubernetes docs, "Specifying a Disruption Budget").
        replicas = deployment["spec"].get("replicas")
        if replicas is None:
            return None
        return math.ceil(replicas * int(value[:-1]) / 100)
    return value


def _selects(selector: dict[str, Any] | None, labels: dict[str, str]) -> bool | None:
    """True if a PDB selector picks pods with these labels, False if not, None if M3 can't tell.

    policy/v1: a missing (null) selector picks no pods; an empty one ({}) picks every pod
    (Kubernetes API reference, PodDisruptionBudgetSpec).
    """
    if selector is None:
        return False
    # matchLabels and matchExpressions must both hold, so one wrong label is enough for False.
    for key, value in selector.get("matchLabels", {}).items():
        if labels.get(key) != value:
            return False
    if selector.get("matchExpressions"):
        return None  # not read in F1: the PDB might select these pods, so the minimum is unknown
    return True


def _claims_in_use(pods: list[dict[str, Any]]) -> set[str]:
    """Names of the PVCs some pod uses ("in active use" = a Pod object uses it, Kubernetes docs)."""
    names = set()
    for pod in pods:
        for volume in pod["spec"].get("volumes", []):
            claim = volume.get("persistentVolumeClaim")
            if claim is not None:
                names.add(claim["claimName"])
    return names


def saved_output(folder: Path) -> Runner:
    """A runner that answers each command from saved kubectl output.

    `folder/index.json` maps each command to the file holding its output.
    """
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))

    def run(command: str) -> str:
        if not is_read_only(command):
            raise ValueError(f"refusing a command that isn't 'kubectl get': {command!r}")
        if command not in index:
            raise LookupError(f"no saved output for: {command!r}")
        return (folder / index[command]).read_text(encoding="utf-8")

    return run


def live_kubectl(context: str, timeout_s: float = 10.0) -> Runner:
    """A runner that calls kubectl on one named context (the disposable dev cluster), read-only.

    The context is always passed explicitly, so a command can't reach another cluster.
    """

    def run(command: str) -> str:
        if not is_read_only(command):
            raise ValueError(f"refusing a command that isn't 'kubectl get': {command!r}")
        argv = shlex.split(command) + ["--context", context]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s, check=False)
        if done.returncode != 0:
            raise RuntimeError(f"kubectl failed: {done.stderr.strip()}")
        return done.stdout

    return run
