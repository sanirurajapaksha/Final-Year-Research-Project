from pathlib import Path

import dotenv
import pytest

from argus.contracts import TelemetryBatch

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"


@pytest.fixture(autouse=True)
def ignore_dotenv(monkeypatch):
    """Tests never read the developer's .env, so they never use a real key or local settings."""

    def skip(*args, **kwargs):
        return False

    monkeypatch.setattr(dotenv, "load_dotenv", skip)


@pytest.fixture
def sample_batch() -> TelemetryBatch:
    return TelemetryBatch.model_validate_json(
        (FIXTURES / "telemetry_sample.json").read_text(encoding="utf-8")
    )
