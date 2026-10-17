from collections import Counter

from argus.context.filters import extract_anomalies
from argus.context.ingest import parse_records
from argus.context.isolator import OFF_GRAPH, OFF_PATH, prune
from argus.context.sdg import ServiceGraph, build_graph
from argus.contracts import AnomalySignal

T = "2026-10-10T10:00:00Z"


def signal(service, name="log_error"):
    return AnomalySignal(service=service, source="log", name=name, timestamp=T)


def keys(signals):
    return Counter((s.service, s.name) for s in signals)


def graph(failing=("cart",), unseen_callees=0):
    return ServiceGraph(
        services={"frontend", "cart", "product-catalog"},
        edges={("frontend", "cart"), ("frontend", "product-catalog")},
        failing=set(failing),
        unseen_callees=unseen_callees,
    )


def test_scenario_01_keeps_all_evidence_and_prunes_all_stage1_noise(scenario_01_batch, scenario_01_truth):
    telemetry = parse_records(scenario_01_batch.records)
    kept, pruned = prune(extract_anomalies(telemetry), build_graph(telemetry.spans))
    expected = scenario_01_truth["stage1_expected"]
    assert keys(kept) == Counter(map(tuple, expected["relevant"]))
    assert keys(p.signal for p in pruned) == Counter(map(tuple, expected["noise"]))
    reasons = {p.signal.service: p.reason for p in pruned}
    assert reasons == {"product-catalog": OFF_PATH, "metrics-server": OFF_GRAPH}


def test_callers_of_the_failing_service_are_kept():
    kept, pruned = prune([signal("frontend"), signal("cart")], graph())
    assert keys(kept) == keys([signal("frontend"), signal("cart")])
    assert pruned == []


def test_no_failing_spans_prunes_nothing():
    signals = [signal("product-catalog"), signal("metrics-server")]
    assert prune(signals, graph(failing=())) == (signals, [])


def test_unseen_callee_keeps_signals_from_outside_the_graph():
    kept, pruned = prune([signal("redis"), signal("product-catalog")], graph(unseen_callees=1))
    assert [s.service for s in kept] == ["redis"]
    assert [(p.signal.service, p.reason) for p in pruned] == [("product-catalog", OFF_PATH)]


def test_order_is_preserved():
    signals = [signal("cart", "b"), signal("frontend", "a"), signal("cart", "a")]
    kept, _ = prune(signals, graph())
    assert kept == signals


def test_empty_anomaly_set():
    assert prune([], graph()) == ([], [])
