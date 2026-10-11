"""Shared data contracts: the typed messages that cross module boundaries.

DRAFT v0. These shapes are a starting point for contract v1, which all four module
owners must agree on. Change a model here only through a PR that every affected owner
approves. See docs/contracts.md.
"""

from argus.contracts.context import AnomalySignal, SemanticContext, ServiceNode
from argus.contracts.diagnosis import DiagnosisResult, Hypothesis, ProposedAction
from argus.contracts.execution import ExecutionResult
from argus.contracts.safety import GateDecision, SafetyVerdict, Z3Result
from argus.contracts.telemetry import (
    CompressedTelemetry,
    K8sEntity,
    LogRecord,
    MetricSample,
    Severity,
    Span,
    SpanKind,
    TelemetryBatch,
    TelemetryRecord,
)

__all__ = [
    "AnomalySignal",
    "CompressedTelemetry",
    "DiagnosisResult",
    "ExecutionResult",
    "GateDecision",
    "Hypothesis",
    "K8sEntity",
    "LogRecord",
    "MetricSample",
    "ProposedAction",
    "SafetyVerdict",
    "SemanticContext",
    "ServiceNode",
    "Severity",
    "Span",
    "SpanKind",
    "TelemetryBatch",
    "TelemetryRecord",
    "Z3Result",
]
