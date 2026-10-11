from argus.context.filters import Thresholds
from argus.context.service import build_context
from argus.contracts import CompressedTelemetry, SemanticContext, TelemetryBatch
from argus.orchestration.service import compress


def test_build_context_returns_a_semantic_context():
    telemetry = CompressedTelemetry(content="", original_size=0, compressed_size=0)
    assert isinstance(build_context(telemetry), SemanticContext)


def test_build_context_runs_stage1_on_m4_output(scenario_01_batch):
    context = build_context(compress(scenario_01_batch))
    assert context.strategy == "stage1"
    assert len(context.kept_signals) == len(context.anomalies) == 8
    assert {"cart", "frontend"} <= set(context.services)
    assert "8 anomalies from 27 records" in context.notes


def test_build_context_round_trips_as_json(scenario_01_batch):
    context = build_context(compress(scenario_01_batch))
    assert SemanticContext.model_validate_json(context.model_dump_json()) == context


def test_build_context_passes_thresholds_through(scenario_01_batch):
    lenient = Thresholds(metrics={}, log_severities=frozenset(), max_restarts=100, crash_statuses=frozenset())
    assert build_context(compress(scenario_01_batch), lenient).kept_signals == []


def test_empty_telemetry_gives_an_empty_context():
    context = build_context(CompressedTelemetry(content="", original_size=0, compressed_size=0))
    assert context.kept_signals == []
    assert "0 anomalies from 0 records" in context.notes


def test_unreadable_telemetry_is_reported_in_notes_not_raised():
    v0 = TelemetryBatch(
        source="v0",
        collected_at="2026-10-10T00:00:00Z",
        records=[{"kind": "event", "object": "pod/geo", "reason": "BackOff"}],
    )
    context = build_context(compress(v0))
    assert context.kept_signals == []
    assert context.notes.startswith("M1 could not read the telemetry: record 0")


def test_malformed_tsv_is_reported_in_notes():
    telemetry = CompressedTelemetry(content="kind\r\nnot-json\r\n", original_size=0, compressed_size=0)
    assert "TSV row 2" in build_context(telemetry).notes
