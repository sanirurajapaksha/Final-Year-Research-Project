import csv
import io
import json

import pytest

from sre_agent.contracts import CompressedTelemetry, ExecutionResult, ProposedAction
from sre_agent.orchestration.service import compress, execute


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
