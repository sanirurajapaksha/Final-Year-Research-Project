import json

from argus.context import report as m1_report
from argus.context.isolator import OFF_GRAPH, OFF_PATH
from argus.context.sdg import ServiceGraph
from argus.context.service import ContextReport, build_report
from argus.contracts import AnomalySignal, CompressedTelemetry, SemanticContext
from argus.orchestration.service import compress

T = "2026-10-10T10:04:00Z"


def rows(data):
    return sorted((row["service"], row["name"], row["kept"], row["reason"]) for row in data["signals"])


def test_scenario_01_report_shows_graph_path_and_every_signal(scenario_01_batch):
    data = m1_report.report_data(build_report(compress(scenario_01_batch)))

    assert (data["records"], data["stage1_count"], data["kept_count"], data["pruned_count"]) == (27, 8, 5, 3)
    assert data["graph"]["edges"] == [
        {"caller": "frontend", "callee": "cart", "on_failing_path": True},
        {"caller": "frontend", "callee": "product-catalog", "on_failing_path": False},
    ]
    assert data["graph"]["failing_path"] == ["cart", "frontend"]
    assert data["graph"]["entry_point"] == "frontend"
    pruned = [(r[0], r[1], r[3]) for r in rows(data) if not r[2]]
    assert pruned == [
        ("metrics-server", "log_error", OFF_GRAPH),
        ("metrics-server", "restart_count", OFF_GRAPH),
        ("product-catalog", "memory_utilization", OFF_PATH),
    ]
    assert {r[3] for r in rows(data) if r[2]} == {m1_report.ON_PATH}
    assert data["context"]["failing_services"] == ["cart", "frontend"]
    json.dumps(data)  # plain data only


def test_stage1_report_has_no_graph(scenario_01_batch):
    data = m1_report.report_data(build_report(compress(scenario_01_batch), strategy="stage1"))
    assert data["graph"] is None
    assert data["pruned_count"] == 0
    assert {r[3] for r in rows(data)} == {m1_report.STAGE1_ONLY}


def test_unreadable_telemetry_gives_an_empty_report_with_the_reason():
    telemetry = CompressedTelemetry(content="kind\r\nnot-json\r\n", original_size=0, compressed_size=0)
    data = m1_report.report_data(build_report(telemetry))
    assert data["signals"] == [] and data["graph"] is None
    assert "TSV row 2" in data["notes"]


def test_kept_reasons_follow_the_pruning_rules():
    signals = [AnomalySignal(service=s, source="log", name="log_error", timestamp=T) for s in ("redis", "db")]
    graph = ServiceGraph(
        services={"cart", "redis"},
        edges={("cart", "redis")},
        failing={"cart"},
        unseen_callees=1,
        unseen_callers={"cart"},
    )
    data = m1_report.report_data(ContextReport(SemanticContext(kept_signals=signals), 2, signals, [], graph))
    assert [(r["service"], r["reason"]) for r in data["signals"]] == [
        ("redis", m1_report.MAYBE_UNSEEN),
        ("db", m1_report.OUTSIDE_KEPT),
    ]
    no_fault = ContextReport(SemanticContext(kept_signals=signals), 2, signals, [], ServiceGraph())
    assert {r["reason"] for r in m1_report.report_data(no_fault)["signals"]} == {m1_report.NO_FAULT_FOUND}
