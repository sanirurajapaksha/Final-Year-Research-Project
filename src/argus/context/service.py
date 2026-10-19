"""M1 entry point.

M4's TSV -> typed records (F1) -> Stage 1 anomaly set (F1) -> service dependency graph and Stage 2
pruning (F2) -> Semantic Context Object.

`build_report` returns the context plus what M1 keeps to itself (the Stage 1 set, the pruned
signals with reasons, the graph) for experiments and the UI. `build_context` returns only the
contract object.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from argus.context.filters import Thresholds, extract_anomalies
from argus.context.ingest import IngestError, ParsedTelemetry, decode_tsv, parse_records
from argus.context.isolator import PrunedSignal, prune
from argus.context.sdg import DEFAULT_LOOKBACK, ServiceGraph, build_graph, is_error, spans_in_window
from argus.contracts import AnomalySignal, CompressedTelemetry, K8sEntity, SemanticContext, ServiceNode, Span

Strategy = Literal["stage1", "failing_path"]
STRATEGIES: tuple[Strategy, ...] = ("stage1", "failing_path")


@dataclass
class ContextReport:
    """One run of M1. Only `context` crosses the contract; the rest stays inside M1."""

    context: SemanticContext
    records: int = 0
    stage1: list[AnomalySignal] = field(default_factory=list)
    pruned: list[PrunedSignal] = field(default_factory=list)
    graph: ServiceGraph | None = None


def build_context(
    telemetry: CompressedTelemetry,
    thresholds: Thresholds | None = None,
    strategy: Strategy = "failing_path",
    lookback: timedelta = DEFAULT_LOOKBACK,
) -> SemanticContext:
    """Turn M4's compressed telemetry into the Semantic Context Object for M2."""
    return build_report(telemetry, thresholds, strategy, lookback).context


def build_report(
    telemetry: CompressedTelemetry,
    thresholds: Thresholds | None = None,
    strategy: Strategy = "failing_path",
    lookback: timedelta = DEFAULT_LOOKBACK,
) -> ContextReport:
    """Run M1 and keep the intermediate results.

    Telemetry M1 can't use (IngestError) gives an empty context whose `notes` say why, so the
    failure is visible to M2 and in the pipeline output instead of stopping the whole run.
    Any other exception is a bug in M1, or an unknown `strategy`, and is raised.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown context strategy {strategy!r}; expected one of {STRATEGIES}")
    try:
        parsed = parse_records(decode_tsv(telemetry.content))
        signals = extract_anomalies(parsed, thresholds)
    except IngestError as error:
        return ContextReport(
            SemanticContext(strategy=strategy, notes=f"M1 could not read the telemetry: {error}")
        )

    if strategy == "stage1":
        context = SemanticContext(
            strategy=strategy,
            kept_signals=signals,
            anomalies=_describe(signals),
            services=sorted({signal.service for signal in signals}),
            notes=f"Stage 1 only: {len(signals)} anomalies from {parsed.total} records.",
        )
        return ContextReport(context, parsed.total, signals)

    # Spans that can't be placed in the alert window can't locate the fault either, so Stage 2 gets
    # no spans and prunes nothing: the Stage 1 anomalies (e.g. an ERROR log) still reach M2.
    window_error = None
    try:
        spans = spans_in_window(parsed.spans, telemetry.alert_time, lookback)
    except IngestError as error:
        spans = []
        window_error = str(error)
    graph = build_graph(spans)
    kept, pruned = prune(signals, graph)
    path = graph.failing_path()
    services = sorted(path | {signal.service for signal in kept})
    context = SemanticContext(
        strategy=strategy,
        kept_signals=kept,
        anomalies=_describe(kept),
        services=services,
        dependencies=sorted(edge for edge in graph.edges if set(edge) <= path),
        failing_services=sorted(graph.failing),
        entry_point=graph.entry_point,
        symptoms=_symptoms(spans),
        nodes=[_node(name, parsed.k8s) for name in services],
        notes=_notes(parsed, signals, kept, spans, graph, telemetry, window_error),
    )
    return ContextReport(context, parsed.total, signals, pruned, graph)


def _describe(signals: list[AnomalySignal]) -> list[str]:
    return [f"{signal.service}: {signal.name} ({signal.evidence})" for signal in signals]


def _symptoms(spans: list[Span]) -> list[str]:
    """What users saw: each failed operation at the edge of the system (a root span), once."""
    ids = {(span.trace_id, span.span_id) for span in spans}
    symptoms = {
        f"{span.service} {span.operation} failed ({_status(span)})"
        for span in spans
        if is_error(span) and (span.trace_id, span.parent_span_id) not in ids
    }
    return sorted(symptoms)


def _status(span: Span) -> str:
    if span.http_status_code is not None and span.http_status_code >= 500:
        return f"HTTP {span.http_status_code}"
    if span.grpc_status_code:
        return f"gRPC status {span.grpc_status_code}"
    return "status ERROR"


def _node(name: str, entities: list[K8sEntity]) -> ServiceNode:
    """A graph node with its Kubernetes state: a Pod that isn't Running if there is one, else any Pod,
    else another object such as the Deployment. Replicas come from the Deployment."""
    own = [entity for entity in entities if entity.service == name]
    pods = [entity for entity in own if entity.resource == "Pod"]
    status = next((pod.status for pod in pods if pod.status != "Running"), None)
    if status is None and (pods or own):
        status = (pods or own)[0].status
    replicas = next((e.replicas for e in own if e.resource == "Deployment" and e.replicas is not None), None)
    return ServiceNode(name=name, k8s_status=status, replicas=replicas)


def _notes(
    parsed: ParsedTelemetry,
    signals: list[AnomalySignal],
    kept: list[AnomalySignal],
    spans: list[Span],
    graph: ServiceGraph,
    telemetry: CompressedTelemetry,
    window_error: str | None,
) -> str:
    notes = [
        f"Stage 2 kept {len(kept)} of {len(signals)} Stage 1 anomalies "
        f"({parsed.total} records, {len(spans)} spans in the window)."
    ]
    if window_error is not None:
        notes.append(f"Spans couldn't be placed in the alert window ({window_error}), so none were used.")
    elif telemetry.alert_time is None:
        notes.append("No alert_time, so every span was used.")
    if not graph.failing:
        notes.append("No failing spans, so the fault couldn't be located and nothing was pruned.")
    if graph.unseen_callees:
        notes.append(
            f"{graph.unseen_callees} failed call(s) had no span from the callee, so anomalies from "
            "services outside the call graph were kept."
        )
    return " ".join(notes)
