"""F2 step 5, Stage 2: keep a Stage 1 anomaly only if its service is on the failing call path.

When M1 can't tell where the fault is, it prunes less rather than risk throwing evidence away:
- no failing spans in the window: nothing is pruned;
- a failed call has no span from its callee: signals from services outside the call graph are
  kept, because one of them may be that unseen callee.
"""

from dataclasses import dataclass

from argus.context.sdg import ServiceGraph
from argus.contracts import AnomalySignal

OFF_PATH = "in the call graph but not on the failing path"
OFF_GRAPH = "not in the call graph"


@dataclass(frozen=True)
class PrunedSignal:
    """A Stage 1 anomaly that Stage 2 removed, and why. Stays inside M1 (experiments, UI)."""

    signal: AnomalySignal
    reason: str


def prune(
    signals: list[AnomalySignal], graph: ServiceGraph
) -> tuple[list[AnomalySignal], list[PrunedSignal]]:
    """Split Stage 1 anomalies into (kept, pruned), keeping their original order."""
    if not graph.failing:
        return list(signals), []

    path = graph.failing_path()
    kept: list[AnomalySignal] = []
    pruned: list[PrunedSignal] = []
    for signal in signals:
        if signal.service in path:
            kept.append(signal)
        elif signal.service in graph.services:
            pruned.append(PrunedSignal(signal, OFF_PATH))
        elif graph.unseen_callees:
            kept.append(signal)
        else:
            pruned.append(PrunedSignal(signal, OFF_GRAPH))
    return kept, pruned
