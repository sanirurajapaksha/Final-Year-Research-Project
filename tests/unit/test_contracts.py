import pytest
from pydantic import TypeAdapter, ValidationError

from argus.contracts import (
    AnomalySignal,
    CompressedTelemetry,
    GateDecision,
    Hypothesis,
    K8sEntity,
    LogRecord,
    MetricSample,
    ProposedAction,
    SafetyVerdict,
    SemanticContext,
    ServiceNode,
    Severity,
    Span,
    SpanKind,
    TelemetryBatch,
    TelemetryRecord,
)


def test_command_is_kept_byte_exact():
    command = 'kubectl  patch deploy geo -n x -p \'{"spec":{"replicas":2}}\'  '
    action = ProposedAction(command=command, is_write=True)
    assert action.command == command


def test_hypothesis_probability_must_be_between_0_and_1():
    with pytest.raises(ValidationError):
        Hypothesis(root_cause="x", probability=1.5)


def test_safety_verdict_requires_a_decision():
    with pytest.raises(ValidationError):
        SafetyVerdict(command="kubectl get pods", reason="missing decision")


def test_safety_verdict_keeps_raw_result_and_decision_separate():
    verdict = SafetyVerdict(command="c", decision=GateDecision.BLOCK, reason="r")
    assert verdict.z3_result is None
    assert verdict.decision is GateDecision.BLOCK


# M1 telemetry records and Semantic Context (contract v1 proposal).

T = "2026-10-10T10:00:00Z"


def span(**overrides):
    fields = dict(
        service="frontend",
        trace_id="t1",
        span_id="s2",
        parent_span_id="s1",
        operation="GetCart",
        span_kind="CLIENT",
        start_time=T,
        duration_ms=12.5,
    )
    return Span(**(fields | overrides))


def test_metric_sample_parses_timestamp_and_value():
    sample = MetricSample(service="cart", name="http_5xx_rate", timestamp=T, value="0.42")
    assert sample.value == 0.42
    assert sample.timestamp.tzinfo is not None


def test_metric_sample_requires_a_value():
    with pytest.raises(ValidationError):
        MetricSample(service="cart", name="http_5xx_rate", timestamp=T)


def test_log_record_accepts_a_known_severity():
    log = LogRecord(service="cart", severity="ERROR", message="CART_ADDR not set", timestamp=T)
    assert log.severity is Severity.ERROR


def test_log_record_rejects_lowercase_severity():
    with pytest.raises(ValidationError):
        LogRecord(service="cart", severity="error", message="m", timestamp=T)


def test_span_keeps_a_failed_client_call():
    failed = span(otel_status_code="ERROR", grpc_status_code=14)
    assert failed.span_kind is SpanKind.CLIENT
    assert failed.otel_status_code == "ERROR"


def test_root_span_has_no_parent():
    assert span(parent_span_id=None, span_kind="SERVER").parent_span_id is None


def test_span_rejects_unknown_span_kind():
    with pytest.raises(ValidationError):
        span(span_kind="SIDEWAYS")


def test_span_rejects_negative_duration():
    with pytest.raises(ValidationError):
        span(duration_ms=-1)


def test_span_rejects_unknown_otel_status():
    with pytest.raises(ValidationError):
        span(otel_status_code="FAILED")


def test_k8s_entity_records_a_crash_looping_pod():
    pod = K8sEntity(
        service="cart",
        name="cart-7f9",
        namespace="default",
        resource="Pod",
        status="CrashLoopBackOff",
        restart_count=5,
    )
    assert pod.restart_count == 5
    assert pod.replicas is None


def test_k8s_entity_rejects_negative_restart_count():
    with pytest.raises(ValidationError):
        K8sEntity(
            service="cart",
            name="cart-7f9",
            namespace="default",
            resource="Pod",
            status="Running",
            restart_count=-1,
        )


@pytest.mark.parametrize(
    ("record", "model"),
    [
        ({"kind": "metric", "service": "s", "name": "cpu", "timestamp": T, "value": 1}, MetricSample),
        ({"kind": "log", "service": "s", "severity": "INFO", "message": "m", "timestamp": T}, LogRecord),
        (span().model_dump(mode="json"), Span),
        (
            {
                "kind": "k8s",
                "service": "s",
                "name": "p",
                "namespace": "n",
                "resource": "Pod",
                "status": "Running",
            },
            K8sEntity,
        ),
    ],
)
def test_telemetry_record_picks_the_model_from_kind(record, model):
    assert isinstance(TypeAdapter(TelemetryRecord).validate_python(record), model)


@pytest.mark.parametrize("record", [{"kind": "event", "service": "s"}, {"service": "s", "value": 1}])
def test_telemetry_record_rejects_unknown_or_missing_kind(record):
    with pytest.raises(ValidationError):
        TypeAdapter(TelemetryRecord).validate_python(record)


def test_telemetry_batch_without_alert_time_still_validates():
    batch = TelemetryBatch(source="fixture", collected_at=T, records=[{"kind": "metric"}])
    assert batch.alert_time is None


def test_compressed_telemetry_carries_alert_time():
    compressed = CompressedTelemetry(content="", original_size=0, compressed_size=0, alert_time=T)
    assert compressed.alert_time is not None


def test_semantic_context_defaults_keep_v0_callers_working():
    context = SemanticContext()
    assert context.anomalies == []
    assert context.fallback_used is False
    assert context.strategy == "failing_path"


def test_semantic_context_round_trips_as_plain_json():
    signal = AnomalySignal(service="cart", source="log", name="log_error", timestamp=T)
    context = SemanticContext(
        kept_signals=[signal],
        nodes=[ServiceNode(name="cart", k8s_status="CrashLoopBackOff")],
        dependencies=[("frontend", "cart")],
        failing_services=["cart"],
        entry_point="frontend",
    )
    assert SemanticContext.model_validate_json(context.model_dump_json()) == context


def test_anomaly_signal_rejects_unknown_source():
    with pytest.raises(ValidationError):
        AnomalySignal(service="cart", source="trace", name="x", timestamp=T)
