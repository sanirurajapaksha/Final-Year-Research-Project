"""M1's output: the Semantic Context Object (M1 -> M4 -> M2).

Plain JSON-friendly fields only: no graph library objects cross the boundary. Pruned signals,
raw counts and timings stay inside M1; M2 receives only what survived pruning.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AnomalySignal(BaseModel):
    """One telemetry signal that crossed a Stage 1 threshold."""

    service: str
    source: Literal["metric", "log", "span", "k8s"]
    # e.g. "http_5xx_rate", "log_error", "CrashLoopBackOff".
    name: str
    value: float | None = None
    timestamp: datetime
    # Short human-readable reason, for M2.
    evidence: str = ""


class ServiceNode(BaseModel):
    """A service in the Service Dependency Graph, with its Kubernetes state if known."""

    name: str
    k8s_status: str | None = None
    replicas: int | None = None


class SemanticContext(BaseModel):
    """Filtered, structured view of the incident that M2 diagnoses from."""

    anomalies: list[str] = []
    services: list[str] = []
    # Edges of the Service Dependency Graph as (caller, callee) pairs.
    dependencies: list[tuple[str, str]] = []
    notes: str = ""
    # Proposed for contract v1.
    symptoms: list[str] = []
    kept_signals: list[AnomalySignal] = []
    nodes: list[ServiceNode] = []
    failing_services: list[str] = []
    # The service the failing requests entered through, if known.
    entry_point: str | None = None
    # True when traces were too sparse and M1 used the static topology instead.
    fallback_used: bool = False
    # The context strategy that produced this object, e.g. "failing_path".
    strategy: str = "failing_path"
