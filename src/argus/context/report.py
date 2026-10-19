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


# Colours for graph_dot, readable on the dashboard's light and dark themes.
FAILING_COLOUR = "#c0392b"
CALLER_COLOUR = "#d68910"
OFF_PATH_COLOUR = "#5d6d7e"
FADED_COLOUR = "#95a5a6"


def graph_dot(data: dict) -> str:
    """The service graph from report_data() as Graphviz DOT text, for the page to draw.

    Red: failing services. Orange: healthy callers on the failing path. Grey: in the graph but off
    the path. Dashed: services with Stage 1 anomalies but no spans, so not in the graph at all.
    Each node says how many of its anomalies were kept and pruned. Empty text when there's no graph.
    """
    graph = data["graph"]
    if graph is None:
        return ""

    counts: dict[str, list[int]] = {}
    for row in data["signals"]:
        kept_and_pruned = counts.setdefault(row["service"], [0, 0])
        if row["kept"]:
            kept_and_pruned[0] += 1
        else:
            kept_and_pruned[1] += 1

    lines = [
        "digraph sdg {",
        '  rankdir=LR; bgcolor="transparent"; nodesep=0.5; ranksep=1.4;',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=16, fontcolor="white",'
        ' margin="0.3,0.15"];',
        "  edge [arrowsize=1.2];",
    ]
    for service in graph["services"]:
        if service in graph["failing_services"]:
            colour = FAILING_COLOUR
        elif service in graph["failing_path"]:
            colour = CALLER_COLOUR
        else:
            colour = OFF_PATH_COLOUR
        label = service + _anomaly_note(counts.get(service))
        extra = ""
        if service == graph["entry_point"]:
            label += "\\nentry point"
            extra = ", peripheries=2"
        lines.append(f'  "{service}" [label="{label}", fillcolor="{colour}", color="{colour}"{extra}];')

    for service in sorted(counts):
        if service not in graph["services"]:
            label = service + "\\n(no spans)" + _anomaly_note(counts[service])
            lines.append(
                f'  "{service}" [label="{label}", style="rounded,dashed", '
                f'color="{FADED_COLOUR}", fontcolor="{FADED_COLOUR}"];'
            )

    for edge in graph["edges"]:
        if edge["on_failing_path"]:
            style = f'color="{FAILING_COLOUR}", penwidth=2.5'
        else:
            style = f'color="{FADED_COLOUR}", style=dashed'
        lines.append(f'  "{edge["caller"]}" -> "{edge["callee"]}" [{style}];')
    lines.append("}")
    return "\n".join(lines)


def _anomaly_note(kept_and_pruned: list[int] | None) -> str:
    if kept_and_pruned is None:
        return ""
    kept, pruned = kept_and_pruned
    parts = []
    if kept:
        parts.append(f"{kept} kept")
    if pruned:
        parts.append(f"{pruned} pruned")
    return "\\n" + ", ".join(parts)
