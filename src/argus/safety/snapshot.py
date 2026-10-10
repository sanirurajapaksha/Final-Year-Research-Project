"""Cluster snapshot: the facts M3 reasons about.

In F1 the snapshot is a hand-written JSON fixture (data/fixtures/m3/). In F2 the Constraint
Extractor produces the same format from read-only cluster queries, so this format is the
contract between the two. Current shape:

    {
      "captured_at": "...",
      "deployments": [
        {"namespace": "...", "name": "...", "replicas": 3, "min_replicas": 2}
      ]
    }

A missing field is allowed: the compiler leaves it unconstrained (fail-safe).
Where "min_replicas" comes from on a live cluster is still open (PodDisruptionBudget,
annotation or project config).
"""

from typing import Any


def deployment_facts(snapshot: dict[str, Any], namespace: str, name: str) -> dict[str, Any] | None:
    """Return the facts for one deployment, or None if the snapshot doesn't contain it."""
    for item in snapshot.get("deployments", []):
        if item.get("namespace") == namespace and item.get("name") == name:
            return {"replicas": item.get("replicas"), "min_replicas": item.get("min_replicas")}
    return None
