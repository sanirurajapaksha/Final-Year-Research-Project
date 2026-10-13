"""F1 Stage 1: threshold predicates that turn typed telemetry into an anomaly set.

Stage 1 has no topology. It keeps every signal that crosses a threshold, including ones
unrelated to the fault; Stage 2 (F2) prunes those using the service dependency graph.
Spans are not Stage 1 input: F2 uses them to build that graph.
"""

from dataclasses import dataclass, field
from datetime import datetime

from argus.context.ingest import IngestError, ParsedTelemetry
from argus.contracts import AnomalySignal, Severity


@dataclass(frozen=True)
class Thresholds:
    """Stage 1 thresholds. Experiments vary these, so they are configuration, not constants."""

    # Metric name -> value above which the sample is an anomaly. Unlisted metrics are ignored.
    metrics: dict[str, float] = field(
        default_factory=lambda: {
            "http_5xx_rate": 0.05,
            "cpu_utilization": 0.90,
            "memory_utilization": 0.90,
        }
    )
    log_severities: frozenset[Severity] = frozenset({Severity.ERROR, Severity.CRITICAL, Severity.FATAL})
    # A pod that restarted more than this many times is an anomaly.
    max_restarts: int = 3
    crash_statuses: frozenset[str] = frozenset({"CrashLoopBackOff", "Error", "OOMKilled"})


def extract_anomalies(
    telemetry: ParsedTelemetry, thresholds: Thresholds | None = None
) -> list[AnomalySignal]:
    """Return every metric, log and k8s signal that crosses a Stage 1 threshold."""
    thresholds = thresholds or Thresholds()
    signals: list[AnomalySignal] = []

    for sample in telemetry.metrics:
        limit = thresholds.metrics.get(sample.name)
        if limit is not None and sample.value > limit:
            signals.append(
                AnomalySignal(
                    service=sample.service,
                    source="metric",
                    name=sample.name,
                    value=sample.value,
                    timestamp=sample.timestamp,
                    evidence=f"{sample.name}={sample.value:g} > {limit:g}",
                )
            )

    for log in telemetry.logs:
        if log.severity in thresholds.log_severities:
            signals.append(
                AnomalySignal(
                    service=log.service,
                    source="log",
                    name=f"log_{log.severity.lower()}",
                    timestamp=log.timestamp,
                    evidence=log.message,
                )
            )

    for entity in telemetry.k8s:
        if entity.status in thresholds.crash_statuses:
            name, evidence = entity.status, f"{entity.resource} {entity.name} is {entity.status}"
        elif entity.restart_count > thresholds.max_restarts:
            name = "restart_count"
            evidence = f"{entity.resource} {entity.name} restarted {entity.restart_count} times"
        else:
            continue
        signals.append(
            AnomalySignal(
                service=entity.service,
                source="k8s",
                name=name,
                value=float(entity.restart_count),
                # k8s snapshots have no per-object timestamp; use the newest telemetry time.
                timestamp=_latest_timestamp(telemetry),
                evidence=evidence,
            )
        )

    return signals


def _latest_timestamp(telemetry: ParsedTelemetry) -> datetime:
    times = [m.timestamp for m in telemetry.metrics] + [entry.timestamp for entry in telemetry.logs]
    times += [s.start_time for s in telemetry.spans]
    if not times:
        # An input problem, not a bug: say so the same way ingestion does.
        raise IngestError("k8s signals need at least one timestamped metric, log or span")
    return max(times)
