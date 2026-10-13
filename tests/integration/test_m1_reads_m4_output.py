"""M1 reads M4's real compressed output and gets back the same typed telemetry."""

from pathlib import Path

import pytest

from argus.context.filters import extract_anomalies
from argus.context.ingest import decode_tsv, parse_records
from argus.contracts import TelemetryBatch
from argus.orchestration.service import compress

SCENARIO_01 = (
    Path(__file__).resolve().parents[2] / "data" / "fixtures" / "m1" / "scenario_01" / "telemetry.json"
)


@pytest.fixture
def scenario_01_batch() -> TelemetryBatch:
    return TelemetryBatch.model_validate_json(SCENARIO_01.read_text(encoding="utf-8"))


def test_m4_tsv_decodes_to_the_original_records(scenario_01_batch):
    compressed = compress(scenario_01_batch)
    assert decode_tsv(compressed.content) == scenario_01_batch.records


def test_anomaly_set_is_the_same_with_or_without_m4(scenario_01_batch):
    direct = extract_anomalies(parse_records(scenario_01_batch.records))
    via_m4 = extract_anomalies(parse_records(decode_tsv(compress(scenario_01_batch).content)))
    assert via_m4 == direct
