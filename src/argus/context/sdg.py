"""F2 steps 2-4: the Service Dependency Graph (SDG) and the failing call path.

An edge (caller, callee) comes from a span whose parent span belongs to a different service: the
parent's service called the child's. That is the CLIENT -> SERVER hop, found without relying on
`span_kind` being set correctly.

Plain sets and dicts, no graph library: the graphs have tens of services, and the result has to
become plain JSON for the contract anyway.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from argus.context.ingest import IngestError
from argus.contracts import Span, SpanKind

# How far before the alert M1 looks for spans. A first guess; experiments may vary it.
DEFAULT_LOOKBACK = timedelta(minutes=5)


def is_error(span: Span) -> bool:
    """True if the span reports a failure: OTel status ERROR, HTTP 5xx or a non-zero gRPC status."""
    return (
        span.otel_status_code == "ERROR"
        or (span.http_status_code is not None and span.http_status_code >= 500)
        or (span.grpc_status_code is not None and span.grpc_status_code != 0)
    )


def spans_in_window(spans: list[Span], alert_time: datetime | None, lookback: timedelta) -> list[Span]:
    """Keep spans that started in [alert_time - lookback, alert_time]; all spans if there's no alert time."""
    if alert_time is None:
        return list(spans)
    if any((span.start_time.tzinfo is None) != (alert_time.tzinfo is None) for span in spans):
        raise IngestError("span start times and alert_time must all have a time zone, or all have none")
    start = alert_time - lookback
    return [span for span in spans if start <= span.start_time <= alert_time]


@dataclass
class ServiceGraph:
    """Who called whom, and which services reported failures."""

    services: set[str] = field(default_factory=set)
    # (caller, callee) pairs.
    edges: set[tuple[str, str]] = field(default_factory=set)
    # Services with at least one error span.
    failing: set[str] = field(default_factory=set)
    # The service that failing requests entered through, if any trace failed.
    entry_point: str | None = None
    # Failed CLIENT spans with no span from the callee: the callee crashed or isn't instrumented,
    # so the graph can't name it.
    unseen_callees: int = 0
    # The services that made those calls.
    unseen_callers: set[str] = field(default_factory=set)

    def possible_unseen_callees(self) -> set[str]:
        """Services an unseen callee could be, from the graph: whatever its callers called elsewhere
        in the window. A callee that answered once and then crashed is in the graph, but may still be
        the one that didn't answer the failed call."""
        return {callee for caller, callee in self.edges if caller in self.unseen_callers}

    def failing_path(self) -> set[str]:
        """The failing services plus every service that calls them, directly or indirectly."""
        callers: dict[str, set[str]] = {}
        for caller, callee in self.edges:
            callers.setdefault(callee, set()).add(caller)
        path = set(self.failing)
        todo = list(self.failing)
        while todo:
            for caller in callers.get(todo.pop(), set()):
                # The `in path` check also stops cycles (a calls b calls a) from looping forever.
                if caller not in path:
                    path.add(caller)
                    todo.append(caller)
        return path


def build_graph(spans: list[Span]) -> ServiceGraph:
    """Build the SDG from spans that are already restricted to the alert window."""
    graph = ServiceGraph()
    by_id = {(span.trace_id, span.span_id): span for span in spans}
    called_elsewhere: set[tuple[str, str]] = set()
    failed_traces: set[str] = set()

    for span in spans:
        graph.services.add(span.service)
        if is_error(span):
            graph.failing.add(span.service)
            failed_traces.add(span.trace_id)
        parent = by_id.get((span.trace_id, span.parent_span_id))
        if parent is not None and parent.service != span.service:
            graph.edges.add((parent.service, span.service))
            called_elsewhere.add((parent.trace_id, parent.span_id))

    unanswered = [
        span
        for span in spans
        if span.span_kind is SpanKind.CLIENT
        and is_error(span)
        and (span.trace_id, span.span_id) not in called_elsewhere
    ]
    graph.unseen_callees = len(unanswered)
    graph.unseen_callers = {span.service for span in unanswered}

    # A root span has no parent in the batch. The most common root service of the failed traces is
    # the entry point; ties go to the alphabetically first name so the result is repeatable.
    roots = Counter(
        span.service
        for span in spans
        if span.trace_id in failed_traces and (span.trace_id, span.parent_span_id) not in by_id
    )
    if roots:
        graph.entry_point = min(roots, key=lambda service: (-roots[service], service))
    return graph
