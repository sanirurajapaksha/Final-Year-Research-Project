import json

from argus.context.service import build_context
from argus.contracts import TelemetryBatch
from argus.diagnosis.core.readonly import is_read_only
from argus.diagnosis.demo import FAKE_READS_LABEL, SCENARIO_READS, demo_diagnose, demo_report, scenario_reads
from argus.orchestration.service import compress

TELEMETRY = SCENARIO_READS.parents[2] / "m1" / "scenario_01" / "telemetry.json"


def scenario_context():
    """The real M4 -> M1 path on scenario_01, as the demo runs it."""
    batch = TelemetryBatch.model_validate_json(TELEMETRY.read_text(encoding="utf-8"))
    return build_context(compress(batch))


def test_canned_reads_are_all_read_only():
    data = json.loads(SCENARIO_READS.read_text(encoding="utf-8"))
    assert data["provenance"].startswith("SYNTHETIC")
    assert all(is_read_only(command) for command in data["reads"])


def test_unknown_read_is_unavailable():
    assert not scenario_reads().run("kubectl get pods -n default").ok


def test_scenario_01_finds_cart_missing_address():
    result = demo_diagnose(scenario_context())
    top = result.hypotheses[0]
    assert top.root_cause.startswith("cart [app-config]")
    assert top.probability >= 0.80


def test_scenario_01_proposes_the_cart_addr_patch():
    writes = [a for a in demo_diagnose(scenario_context()).actions if a.is_write]
    assert len(writes) == 1
    assert "CART_ADDR" in writes[0].command and "redis-cart:6379" in writes[0].command


def test_report_is_labelled_plain_data():
    report = demo_report(scenario_context())
    json.dumps(report)  # plain data only: the dashboard and tests can use it as is
    assert report["reads_source"] == FAKE_READS_LABEL
    assert report["stop_reason"] == "confident"
    assert report["hypotheses"][0]["component"] == "cart"
    assert [r["ok"] for r in report["reads"]] == [True, True, True]
