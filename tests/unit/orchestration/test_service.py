import csv
import io
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from argus.contracts import CompressedTelemetry, ExecutionResult, ProposedAction, TelemetryBatch
from argus.contracts.telemetry import K8sEntity, LogRecord, MetricSample, Span
from argus.orchestration.service import compress, execute


def test_compress_returns_compressed_telemetry(sample_batch):
    assert isinstance(compress(sample_batch), CompressedTelemetry)


def read_records(content):
    rows = list(csv.reader(io.StringIO(content, newline=""), delimiter="\t"))
    if not rows:
        return []
    columns = rows[0]
    return [
        {key: json.loads(cell) for key, cell in zip(columns, row, strict=True) if cell != ""}
        for row in rows[1:]
    ]


def assert_json_equal(actual, expected):
    """Check every JSON value and its exact type, including nested values."""
    assert type(actual) is type(expected)
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_json_equal(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected, strict=True):
            assert_json_equal(actual_item, expected_item)
    else:
        assert actual == expected


@pytest.mark.parametrize(
    "actual,expected", [(True, 1), (1, True), (True, 1.0), (1.0, True), (1, 1.0), (1.0, 1)]
)
def test_json_comparison_rejects_equal_values_with_different_types(actual, expected):
    with pytest.raises(AssertionError):
        assert_json_equal({"nested": [actual]}, {"nested": [expected]})


def test_compress_round_trips_sample_and_column_order(sample_batch):
    result = compress(sample_batch)
    assert result.format == "tsv"
    assert read_records(result.content) == sample_batch.records
    assert next(csv.reader(io.StringIO(result.content), delimiter="\t")) == [
        "kind",
        "service",
        "name",
        "value",
        "message",
        "object",
        "reason",
    ]


def test_compress_preserves_values_and_types(sample_batch):
    sample_batch.records = [
        {
            "integer": 7,
            "float": 7.0,
            "boolean": True,
            "false": False,
            "string": "7",
            "list": [True, 1, 1.0, "two", None, False, {"values": [True, 1, 1.0]}],
            "object": {"nested": [3.5, {"boolean": True, "integer": 1, "float": 1.0}]},
        }
    ]
    restored = read_records(compress(sample_batch).content)
    assert_json_equal(restored, sample_batch.records)


def test_compress_preserves_input_and_separated_duplicates(sample_batch):
    repeated = {"kind": "log", "details": {"values": [True, 1, 1.0, {"message": "retry"}]}}
    sample_batch.records = [
        repeated,
        {"kind": "metric", "details": {"values": [False, 2, 2.0]}},
        deepcopy(repeated),
    ]
    before = deepcopy(sample_batch)

    result = compress(sample_batch)

    assert sample_batch.source == before.source
    assert sample_batch.collected_at == before.collected_at
    assert_json_equal(sample_batch.records, before.records)
    assert_json_equal(read_records(result.content), before.records)


def test_compress_distinguishes_missing_null_and_empty_string(sample_batch):
    sample_batch.records = [{"value": None}, {"value": ""}, {}, {"other": 0}]
    result = compress(sample_batch)
    rows = list(csv.reader(io.StringIO(result.content), delimiter="\t"))
    assert rows == [["value", "other"], ["null", ""], ['""', ""], ["", ""], ["", "0"]]
    assert read_records(result.content) == sample_batch.records


def test_compress_preserves_tabs_newlines_and_quotes(sample_batch):
    sample_batch.records = [{"key\twith\nlines": 'value\twith\nlines\r\nand "quotes"'}]
    assert read_records(compress(sample_batch).content) == sample_batch.records


@pytest.mark.parametrize("records", [[], [{}], [{}, {}]])
def test_compress_handles_empty_records(sample_batch, records):
    sample_batch.records = records
    result = compress(sample_batch)
    assert read_records(result.content) == records
    assert result.original_size == len(json.dumps(records, ensure_ascii=False).encode("utf-8"))
    assert result.compressed_size == len(result.content.encode("utf-8"))
    if not records:
        assert result.content == ""
        assert result.original_size == 2
        assert result.compressed_size == 0


def test_compress_measures_utf8_bytes(sample_batch):
    sample_batch.records = [{"message": "caf\u00e9 \U0001f680"}]
    result = compress(sample_batch)
    original = json.dumps(sample_batch.records, ensure_ascii=False)
    assert result.original_size == len(original.encode("utf-8")) > len(original)
    assert result.compressed_size == len(result.content.encode("utf-8")) > len(result.content)
    assert read_records(result.content) == sample_batch.records


def test_compress_rejects_values_that_are_not_json(sample_batch):
    sample_batch.records = [{"value": object()}]
    with pytest.raises(TypeError):
        compress(sample_batch)


def test_execute_returns_an_execution_result():
    action = ProposedAction(command="kubectl get pods -n demo", is_write=False)
    assert isinstance(execute(action), ExecutionResult)


def test_saved_experiment_tsv_matches_fixture(sample_batch):
    root = Path(__file__).resolve().parents[3]
    results = root / "experiments/2026-10-10_m4_minimal_f1/results"
    payload = (results / "telemetry_sample.tsv").read_bytes()
    content = payload.decode("utf-8")
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    columns = next(csv.reader(io.StringIO(content, newline=""), delimiter="\t"))
    assert columns == list(dict.fromkeys(key for record in sample_batch.records for key in record))
    assert_json_equal(read_records(content), sample_batch.records)
    assert len(payload) == summary["compressed_size_utf8_bytes"] == 228
    original = json.dumps(sample_batch.records, ensure_ascii=False).encode("utf-8")
    assert len(original) == summary["original_size_utf8_bytes"] == 241
    assert payload == compress(sample_batch).content.encode("utf-8")


@pytest.mark.parametrize(
    "alert_fields",
    [{}, {"alert_time": None}, {"alert_time": datetime(2026, 10, 13, 12, 30, tzinfo=UTC)}],
)
@pytest.mark.parametrize(
    "records",
    [
        [],
        [
            {
                "kind": "log",
                "service": "checkout",
                "severity": "ERROR",
                "message": "alert",
                "timestamp": "2026-10-13T12:30:00Z",
            }
        ],
    ],
)
def test_compress_preserves_contract_alert_time(sample_batch, alert_fields, records):
    fields = sample_batch.model_dump(exclude={"alert_time", "records"})
    batch = TelemetryBatch(**fields, **alert_fields, records=records)
    before = deepcopy(batch)

    result = compress(batch)

    assert result.alert_time == batch.alert_time
    assert type(result.alert_time) is type(batch.alert_time)
    assert batch == before


@pytest.mark.parametrize("exclude_unset", [False, True])
def test_compress_preserves_all_contract_record_fields(sample_batch, exclude_unset):
    timestamp = "2026-10-13T12:30:00Z"
    metric = MetricSample(
        kind="metric",
        service="checkout",
        name="request_latency",
        timestamp=timestamp,
        value=1.0,
        labels={"route": "/café", "method": "GET"},
    )
    log = LogRecord(
        kind="log",
        service="checkout",
        severity="ERROR",
        message="retry\tfailed\n🚀",
        timestamp=timestamp,
    )
    span = Span(
        kind="span",
        service="checkout",
        trace_id="trace-1",
        span_id="span-1",
        parent_span_id="parent-1",
        operation="GET /checkout",
        span_kind="SERVER",
        start_time=timestamp,
        duration_ms=7.0,
        otel_status_code="ERROR",
        http_status_code=503,
        grpc_status_code=14,
    )
    k8s = K8sEntity(
        kind="k8s",
        service="checkout",
        name="checkout-1",
        namespace="demo",
        resource="Pod",
        status="CrashLoopBackOff",
        restart_count=3,
        replicas=2,
    )
    root_span = Span(
        kind="span",
        service="checkout",
        trace_id="trace-2",
        span_id="span-2",
        operation="root",
        span_kind="INTERNAL",
        start_time=timestamp,
        duration_ms=0.0,
    )
    default_metric = MetricSample(
        kind="metric", service="checkout", name="requests", timestamp=timestamp, value=0.0
    )
    default_k8s = K8sEntity(
        kind="k8s",
        service="checkout",
        name="checkout-2",
        namespace="demo",
        resource="Pod",
        status="Running",
    )
    records = [
        record.model_dump(mode="json", exclude_unset=exclude_unset)
        for record in [metric, log, span, k8s, root_span, default_metric, default_k8s, log]
    ]
    sample_batch.records = records
    before = deepcopy(records)

    result = compress(sample_batch)

    rows = list(csv.reader(io.StringIO(result.content, newline=""), delimiter="\t"))
    assert rows[0] == list(dict.fromkeys(key for record in records for key in record))
    assert len(rows) == len(records) + 1
    assert_json_equal(read_records(result.content), before)
    assert_json_equal(sample_batch.records, before)
