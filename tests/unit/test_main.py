import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from argus import __main__ as entrypoint


@pytest.mark.parametrize(
    "content,error_type,location",
    [
        pytest.param('{"source":', "json_invalid", (), id="malformed-json"),
        pytest.param("", "json_invalid", (), id="empty-file"),
        pytest.param(
            '{"collected_at":"2026-10-10T00:00:00Z"}',
            "missing",
            ("source",),
            id="missing-source",
        ),
        pytest.param('{"source":"test"}', "missing", ("collected_at",), id="missing-time"),
        pytest.param(
            '{"source":"test","collected_at":"2026-10-10T00:00:00Z","records":{}}',
            "list_type",
            ("records",),
            id="records-object",
        ),
        pytest.param(
            '{"source":"test","collected_at":"2026-10-10T00:00:00Z","records":[1]}',
            "dict_type",
            ("records", 0),
            id="record-not-object",
        ),
        pytest.param(
            '{"source":"test","collected_at":"2026-10-10T00:00:00Z","records":null}',
            "list_type",
            ("records",),
            id="null-records",
        ),
    ],
)
def test_main_rejects_invalid_telemetry_before_pipeline(tmp_path, monkeypatch, content, error_type, location):
    path = tmp_path / "telemetry.json"
    path.write_text(content, encoding="utf-8")
    pipeline = Mock()
    monkeypatch.setattr(entrypoint, "run_once", pipeline)

    with pytest.raises(ValidationError) as caught:
        entrypoint.main([str(path)])

    assert [(error["type"], error["loc"]) for error in caught.value.errors()] == [(error_type, location)]
    pipeline.assert_not_called()


@pytest.mark.parametrize("include_records", [True, False], ids=["empty-records", "default-records"])
def test_main_loads_empty_batch(tmp_path, monkeypatch, include_records):
    payload = {"source": "test", "collected_at": "2026-10-10T00:00:00Z"}
    if include_records:
        payload["records"] = []
    path = tmp_path / "telemetry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    pipeline = Mock(wraps=entrypoint.run_once)
    monkeypatch.setattr(entrypoint, "run_once", pipeline)

    assert entrypoint.main([str(path)]) == 0

    pipeline.assert_called_once()
    assert pipeline.call_args.args[0].records == []
