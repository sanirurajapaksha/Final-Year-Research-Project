from datetime import UTC, datetime

import pytest

from argus.context.filters import Thresholds
from argus.context.isolator import OFF_GRAPH, OFF_PATH
from argus.context.service import build_context, build_report
from argus.contracts import CompressedTelemetry, SemanticContext, ServiceNode, TelemetryBatch
from argus.orchestration.service import compress


def test_build_context_returns_a_semantic_context():
    telemetry = CompressedTelemetry(content="", original_size=0, compressed_size=0)
    assert isinstance(build_context(telemetry), SemanticContext)


def test_build_context_runs_stage1_on_m4_output(scenario_01_batch):
    context = build_context(compress(scenario_01_batch), strategy="stage1")
    assert context.strategy == "stage1"
    assert len(context.kept_signals) == len(context.anomalies) == 8
    assert {"cart", "frontend"} <= set(context.services)
    assert "8 anomalies from 27 records" in context.notes
    assert context.dependencies == context.nodes == context.failing_services == []


def test_failing_path_is_the_default_strategy(scenario_01_batch):
    assert build_context(compress(scenario_01_batch)).strategy == "failing_path"


def test_failing_path_context_for_scenario_01(scenario_01_batch, scenario_01_truth):
    context = build_context(compress(scenario_01_batch))
    relevant = sorted(map(tuple, scenario_01_truth["stage1_expected"]["relevant"]))
    assert sorted((s.service, s.name) for s in context.kept_signals) == relevant
    assert len(context.anomalies) == 5
    assert context.services == context.failing_services == ["cart", "frontend"]
    assert context.dependencies == [("frontend", "cart")]
    assert context.entry_point == "frontend"
    assert context.symptoms == ["frontend GET /cart failed (HTTP 500)"]
    assert context.nodes == [
        ServiceNode(name="cart", k8s_status="Running"),
        ServiceNode(name="frontend", k8s_status="Available", replicas=1),
    ]
    assert context.fallback_used is False
    assert context.notes == "Stage 2 kept 5 of 8 Stage 1 anomalies (27 records, 6 spans in the window)."


def test_report_keeps_what_the_contract_leaves_out(scenario_01_batch):
    report = build_report(compress(scenario_01_batch))
    assert (report.records, len(report.stage1), len(report.context.kept_signals)) == (27, 8, 5)
    pruned = sorted((p.signal.service, p.signal.name, p.reason) for p in report.pruned)
    assert pruned == [
        ("metrics-server", "log_error", OFF_GRAPH),
        ("metrics-server", "restart_count", OFF_GRAPH),
        ("product-catalog", "memory_utilization", OFF_PATH),
    ]
    assert report.graph.entry_point == "frontend"


def test_spans_after_the_alert_are_left_out(scenario_01_batch):
    early = scenario_01_batch.model_copy(update={"alert_time": datetime(2026, 10, 10, 10, 4, tzinfo=UTC)})
    context = build_context(compress(early))
    assert len(context.kept_signals) == 8
    assert context.failing_services == []
    assert "0 spans in the window" in context.notes
    assert "nothing was pruned" in context.notes


def test_without_alert_time_every_span_is_used(scenario_01_batch):
    batch = scenario_01_batch.model_copy(update={"alert_time": None})
    context = build_context(compress(batch))
    assert len(context.kept_signals) == 5
    assert "No alert_time" in context.notes


def test_unknown_strategy_is_a_caller_bug(scenario_01_batch):
    with pytest.raises(ValueError, match="unknown context strategy"):
        build_context(compress(scenario_01_batch), strategy="top_k")


def test_build_context_round_trips_as_json(scenario_01_batch):
    context = build_context(compress(scenario_01_batch))
    assert SemanticContext.model_validate_json(context.model_dump_json()) == context


def test_build_context_passes_thresholds_through(scenario_01_batch):
    lenient = Thresholds(metrics={}, log_severities=frozenset(), max_restarts=100, crash_statuses=frozenset())
    assert build_context(compress(scenario_01_batch), lenient).kept_signals == []


def test_empty_telemetry_gives_an_empty_context():
    context = build_context(CompressedTelemetry(content="", original_size=0, compressed_size=0))
    assert context.kept_signals == []
    assert context.notes.startswith("Stage 2 kept 0 of 0 Stage 1 anomalies (0 records")


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


def test_a_bug_inside_m1_is_raised_not_hidden_in_notes(scenario_01_batch, monkeypatch):
    def broken_filter(*_args):
        raise ValueError("bug")

    monkeypatch.setattr("argus.context.service.extract_anomalies", broken_filter)
    with pytest.raises(ValueError, match="bug"):
        build_context(compress(scenario_01_batch))
