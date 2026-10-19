"""M1's run as plain data (dicts and lists) for the dashboard page and for tests.

Everything here is built from a `ContextReport`: the service graph, the failing path, and every
Stage 1 anomaly marked kept or pruned with the reason. Only `context` is what M2 receives.
"""

from argus.context.sdg import ServiceGraph
from argus.context.service import ContextReport
from argus.contracts import AnomalySignal

# Why Stage 2 kept a signal. The rules are the ones in isolator.prune, in the same order.
STAGE1_ONLY = "Stage 1 only: no Stage 2 pruning"
NO_FAULT_FOUND = "no failing spans, so nothing was pruned"
ON_PATH = "on the failing path"
MAYBE_UNSEEN = "may be the callee of a failed call that got no answer"
OUTSIDE_KEPT = "not in the call graph, but a failed call got no answer"


def report_data(report: ContextReport) -> dict:
    """The whole M1 run, JSON-ready."""
    context = report.context
    signals = []
    for signal in report.stage1:
        reason = _why_pruned(signal, report)
        if reason is None:
            signals.append(_signal_row(signal, kept=True, reason=_why_kept(signal, report.graph)))
        else:
            signals.append(_signal_row(signal, kept=False, reason=reason))

    return {
        "strategy": context.strategy,
        "records": report.records,
        "notes": context.notes,
        "stage1_count": len(report.stage1),
        "kept_count": len(context.kept_signals),
        "pruned_count": len(report.pruned),
        "graph": _graph_data(report.graph),
        "signals": signals,
        "context": context.model_dump(mode="json"),
    }


def _graph_data(graph: ServiceGraph | None) -> dict | None:
    if graph is None:
        return None
    path = graph.failing_path()
    edges = []
    for caller, callee in sorted(graph.edges):
        on_path = caller in path and callee in path
        edges.append({"caller": caller, "callee": callee, "on_failing_path": on_path})
    return {
        "services": sorted(graph.services),
        "edges": edges,
        "failing_services": sorted(graph.failing),
        "entry_point": graph.entry_point,
        "failing_path": sorted(path),
        "unseen_callees": graph.unseen_callees,
    }


def _signal_row(signal: AnomalySignal, kept: bool, reason: str) -> dict:
    return {
        "service": signal.service,
        "source": signal.source,
        "name": signal.name,
        "value": signal.value,
        "evidence": signal.evidence,
        "kept": kept,
        "reason": reason,
    }


def _why_pruned(signal: AnomalySignal, report: ContextReport) -> str | None:
    """The pruning reason if Stage 2 removed this exact signal, else None."""
    for item in report.pruned:
        if item.signal is signal:
            return item.reason
    return None


def _why_kept(signal: AnomalySignal, graph: ServiceGraph | None) -> str:
    if graph is None:
        return STAGE1_ONLY
    if not graph.failing:
        return NO_FAULT_FOUND
    if signal.service in graph.failing_path():
        return ON_PATH
    if signal.service in graph.possible_unseen_callees():
        return MAYBE_UNSEEN
    return OUTSIDE_KEPT
