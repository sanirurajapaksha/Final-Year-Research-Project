import json
from pathlib import Path

import pytest

from argus.contracts import TelemetryBatch

SCENARIO_01 = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "m1" / "scenario_01"


@pytest.fixture
def scenario_01_batch() -> TelemetryBatch:
    return TelemetryBatch.model_validate_json((SCENARIO_01 / "telemetry.json").read_text(encoding="utf-8"))


@pytest.fixture
def scenario_01_truth() -> dict:
    return json.loads((SCENARIO_01 / "ground_truth.json").read_text(encoding="utf-8"))
