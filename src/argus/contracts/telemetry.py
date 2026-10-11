"""Telemetry as it enters the system (benchmark -> M4) and after M4 compresses it (M4 -> M1).

`TelemetryBatch.records` stays a list of plain dicts so M4 can convert it to TSV without
knowing the record types. Each dict follows one of the typed record models below, chosen by
its `kind` field. M1 validates every record into its typed model with `TelemetryRecord`.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class MetricSample(BaseModel):
    """One Prometheus-style sample: a number for one series at one moment."""

    kind: Literal["metric"] = "metric"
    service: str
    name: str
    labels: dict[str, str] = {}
    timestamp: datetime
    value: float


class Severity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"


class LogRecord(BaseModel):
    """One log line (Loki style)."""

    kind: Literal["log"] = "log"
    service: str
    severity: Severity
    message: str
    timestamp: datetime


class SpanKind(StrEnum):
    CLIENT = "CLIENT"
    SERVER = "SERVER"
    INTERNAL = "INTERNAL"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


class Span(BaseModel):
    """One timed operation in a trace (Jaeger / OpenTelemetry)."""

    kind: Literal["span"] = "span"
    service: str
    trace_id: str
    span_id: str
    # None for a root span.
    parent_span_id: str | None = None
    operation: str
    # CLIENT in the caller, SERVER in the callee. M1 draws dependency edges from these hops.
    span_kind: SpanKind
    start_time: datetime
    duration_ms: float = Field(ge=0)
    otel_status_code: Literal["OK", "ERROR", "UNSET"] = "UNSET"
    http_status_code: int | None = None
    grpc_status_code: int | None = None


class K8sEntity(BaseModel):
    """The state of one Kubernetes object (from `kubectl get ... -o json`)."""

    kind: Literal["k8s"] = "k8s"
    service: str
    name: str
    namespace: str
    # The Kubernetes object type, e.g. "Pod" or "Deployment".
    resource: str
    # e.g. "Running", "CrashLoopBackOff".
    status: str
    restart_count: int = Field(default=0, ge=0)
    replicas: int | None = Field(default=None, ge=0)


# Any one telemetry record. Pydantic reads `kind` and validates against the matching model.
TelemetryRecord = Annotated[MetricSample | LogRecord | Span | K8sEntity, Field(discriminator="kind")]


class TelemetryBatch(BaseModel):
    """Raw telemetry from the benchmark environment, before any processing."""

    source: str
    collected_at: datetime
    # When the alert fired. M1 looks at signals in [alert_time - window, alert_time].
    alert_time: datetime | None = None
    # Each record is a dict shaped like one TelemetryRecord, chosen by its "kind".
    records: list[dict[str, Any]] = []


class CompressedTelemetry(BaseModel):
    """M4's preprocessed and compressed telemetry, handed to M1.

    Fields that M1 or M3 rely on must survive compression unchanged (lossless for those fields).
    """

    format: str = "tsv"
    content: str
    original_size: int
    compressed_size: int
    # Copied unchanged from TelemetryBatch.alert_time.
    alert_time: datetime | None = None
