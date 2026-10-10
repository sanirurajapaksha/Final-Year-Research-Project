"""Step 1: Constraint Extractor (no LLM).

Reads the live cluster to build the invariants and the current state S0: active vs minimum
replicas, service port bindings, protected namespaces, node capacity, PVC bindings.

Read-only verbs only: get, list, watch. This module must never change the cluster.
"""

from typing import Any


def extract(namespace: str) -> dict[str, Any]:
    """Return a snapshot of the cluster facts M3 needs for one namespace."""
    raise NotImplementedError("Constraint Extractor not implemented yet")
