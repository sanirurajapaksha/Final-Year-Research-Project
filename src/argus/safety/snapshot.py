"""Cluster snapshot: the facts M3 reasons about.

In F1 the snapshot is a hand-written JSON fixture (data/fixtures/m3/). In F2 the Constraint
Extractor produces the same format from read-only cluster queries, so this format is the
contract between the two. Current shape:

    {
      "captured_at": "...",
      "deployments": [
        {"namespace": "...", "name": "...", "replicas": 3, "min_replicas": 2, "max_unavailable": 1}
      ],
      "pvcs": [
        {"namespace": "...", "name": "...", "in_use": true}
      ]
    }

A missing field is allowed: the compiler leaves it unconstrained (fail-safe).
Where "min_replicas" comes from on a live cluster is still open (PodDisruptionBudget,
annotation or project config). "in_use" means a Pod object exists that uses the PVC
(the Kubernetes docs' definition of "in active use"); the extractor will work it out from the pods.
"max_unavailable" is the deployment's rolling-update maxUnavailable: a number of pods or a
percentage string such as "25%" (the compiler converts it).
The protected namespaces are M3 policy, not cluster facts, so they live in policy.py.
"""

from typing import Any


def facts_for(snapshot: dict[str, Any], kind: str, namespace: str, name: str) -> dict[str, Any] | None:
    """Return the facts the compiler needs for one target, or None if the snapshot doesn't contain it."""
    if kind == "deployment":
        return deployment_facts(snapshot, namespace, name)
    if kind == "pvc":
        return pvc_facts(snapshot, namespace, name)
    # Pods and namespaces: their only F1 rule (protected namespaces) needs no facts from the snapshot.
    return {}


def deployment_facts(snapshot: dict[str, Any], namespace: str, name: str) -> dict[str, Any] | None:
    """Return the facts for one deployment, or None if the snapshot doesn't contain it."""
    for item in snapshot.get("deployments", []):
        if item.get("namespace") == namespace and item.get("name") == name:
            return {
                "replicas": item.get("replicas"),
                "min_replicas": item.get("min_replicas"),
                "max_unavailable": item.get("max_unavailable"),
            }
    return None


def pvc_facts(snapshot: dict[str, Any], namespace: str, name: str) -> dict[str, Any] | None:
    """Return the facts for one PVC, or None if the snapshot doesn't contain it."""
    for item in snapshot.get("pvcs", []):
        if item.get("namespace") == namespace and item.get("name") == name:
            return {"in_use": item.get("in_use")}
    return None
