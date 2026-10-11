from collections import Counter

import pytest

from argus.context.filters import Thresholds, extract_anomalies
from argus.context.ingest import parse_records

T = "2026-10-10T10:00:00Z"


def keys(signals):
    return Counter((signal.service, signal.name) for signal in signals)


def test_scenario_01_flags_exactly_the_expected_stage1_signals(scenario_01_batch, scenario_01_truth):
    signals = extract_anomalies(parse_records(scenario_01_batch.records))
    expected = scenario_01_truth["stage1_expected"]
    assert keys(signals) == Counter(map(tuple, expected["relevant"] + expected["noise"]))


def test_scenario_01_drops_warn_logs_normal_metrics_and_spans(scenario_01_batch):
    signals = extract_anomalies(parse_records(scenario_01_batch.records))
    services = {signal.service for signal in signals}
    assert "coredns" not in services
    assert "checkout" not in services
    assert all(signal.source != "span" for signal in signals)


def test_custom_thresholds_change_what_is_flagged():
    telemetry = parse_records(
        [{"kind": "metric", "service": "cart", "name": "cpu_utilization", "timestamp": T, "value": 0.6}]
    )
    assert extract_anomalies(telemetry) == []
    strict = Thresholds(metrics={"cpu_utilization": 0.5})
    assert keys(extract_anomalies(telemetry, strict)) == Counter({("cart", "cpu_utilization"): 1})


def test_crash_looping_pod_is_flagged_even_with_few_restarts():
    telemetry = parse_records(
        [
            {"kind": "log", "service": "cart", "severity": "INFO", "message": "start", "timestamp": T},
            {
                "kind": "k8s",
                "service": "cart",
                "name": "cart-1",
                "namespace": "default",
                "resource": "Pod",
                "status": "CrashLoopBackOff",
                "restart_count": 1,
            },
        ]
    )
    [signal] = extract_anomalies(telemetry)
    assert (signal.name, signal.source) == ("CrashLoopBackOff", "k8s")


def test_empty_telemetry_gives_no_anomalies():
    assert extract_anomalies(parse_records([])) == []


def test_metric_at_exactly_the_threshold_is_not_flagged():
    telemetry = parse_records(
        [{"kind": "metric", "service": "cart", "name": "http_5xx_rate", "timestamp": T, "value": 0.05}]
    )
    assert extract_anomalies(telemetry) == []


def test_unknown_metric_name_is_ignored():
    telemetry = parse_records(
        [{"kind": "metric", "service": "cart", "name": "queue_depth", "timestamp": T, "value": 1e9}]
    )
    assert extract_anomalies(telemetry) == []


def test_k8s_signal_without_any_timestamped_record_fails_loudly():
    telemetry = parse_records(
        [
            {
                "kind": "k8s",
                "service": "cart",
                "name": "cart-1",
                "namespace": "default",
                "resource": "Pod",
                "status": "OOMKilled",
            }
        ]
    )
    with pytest.raises(ValueError, match="timestamped"):
        extract_anomalies(telemetry)
