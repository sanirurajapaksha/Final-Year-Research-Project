from pathlib import Path

import pytest

from sre_agent.contracts import TelemetryBatch

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"


@pytest.fixture
def sample_batch() -> TelemetryBatch:
    return TelemetryBatch.model_validate_json(
        (FIXTURES / "telemetry_sample.json").read_text(encoding="utf-8")
    )
