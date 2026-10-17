"""Optional demo checks: install .[demo,dev] to include browser-app tests."""

from pathlib import Path

import pytest

from argus.contracts import TelemetryBatch
from argus.orchestration.dashboard import measurements
from argus.orchestration.dashboard.measurements import DEFAULT_FIXTURE, measure


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


@pytest.fixture(params=["package", "legacy"])
def dashboard_path(request):
    if request.param == "legacy":
        return Path(__file__).resolve().parents[2] / "demo/app.py"
    return Path(measurements.__file__).with_name("app.py")


def test_dashboard_interactions(dashboard_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(dashboard_path).run(timeout=30)
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


def test_dashboard_invalid_input(monkeypatch, dashboard_path):
    pytest.importorskip("streamlit")
    from unittest.mock import Mock

    from streamlit.testing.v1 import AppTest

    invalid = Mock()
    invalid.read_bytes.return_value = b'{"records": [{"kind": "unsupported"}]}'
    monkeypatch.setattr(measurements, "DEFAULT_FIXTURE", invalid)
    app = AppTest.from_file(dashboard_path).run(timeout=30)
    assert not app.exception
    assert any("Cannot process telemetry" in error.value for error in app.error)
    assert not app.metric
