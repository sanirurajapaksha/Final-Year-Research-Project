"""Optional demo checks: install .[demo,dev] to include browser-app tests."""

import pytest
from demo.measurements import DEFAULT_FIXTURE, measure

from argus.contracts import TelemetryBatch


def test_real_fixture_measurements():
    batch = TelemetryBatch.model_validate_json(DEFAULT_FIXTURE.read_bytes())
    output = measure(batch)
    assert (output["compact_json_bytes"], output["default_json_bytes"], output["tsv_bytes"]) == (
        4438,
        4798,
        3746,
    )
    assert all(output["checks"].values())


def test_empty_records():
    batch = TelemetryBatch.model_validate_json(DEFAULT_FIXTURE.read_bytes())
    batch.records = []
    output = measure(batch)
    assert output["tsv_bytes"] == 0
    assert all(output["checks"].values())


def test_invalid_record_rejected():
    batch = TelemetryBatch.model_validate_json(DEFAULT_FIXTURE.read_bytes())
    batch.records = [{"kind": "unsupported"}]
    with pytest.raises(ValueError, match="not valid telemetry"):
        measure(batch)


def test_dashboard_interactions():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(DEFAULT_FIXTURE.parents[4] / "demo/app.py").run(timeout=30)
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["27", "4,438 B", "3,746 B", "15.59%"]
    assert len(app.success) == 4
    app.text_input[0].set_value("no-matching-service-xyz").run()
    assert not app.exception
    assert any(info.value == "No matching records." for info in app.info)
    app.radio[0].set_value("Upload JSON").run()
    assert not app.exception
    assert not app.metric
    assert any("Upload a contract" in info.value for info in app.info)


def test_dashboard_invalid_input(monkeypatch):
    pytest.importorskip("streamlit")
    from unittest.mock import Mock

    import demo.measurements
    from streamlit.testing.v1 import AppTest

    invalid = Mock()
    invalid.read_bytes.return_value = b'{"records": [{"kind": "unsupported"}]}'
    monkeypatch.setattr(demo.measurements, "DEFAULT_FIXTURE", invalid)
    app = AppTest.from_file(DEFAULT_FIXTURE.parents[4] / "demo/app.py").run(timeout=30)
    assert not app.exception
    assert any("Cannot process telemetry" in error.value for error in app.error)
    assert not app.metric
