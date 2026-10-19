import json

from argus.context.service import build_context
from argus.contracts import TelemetryBatch
from argus.diagnosis.core.readonly import is_read_only
from argus.diagnosis.demo import (
    FAKE_READS_LABEL,
    SCENARIO_READS,
    demo_diagnose,
    demo_report,
    prior_beliefs,
    read_verdicts,
    scenario_reads,
)
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


def test_prior_is_the_first_belief_even_for_a_later_hypothesis():
    report = {
        "belief_rounds": [
            {"evidence": "", "verdicts": {}, "belief": {"H1": 0.5, "H0": 0.5}},
            {"evidence": "E1", "verdicts": {"H1": "strong-refute"}, "belief": {"H1": 0.1, "H0": 0.9}},
            {"evidence": "", "verdicts": {}, "belief": {"H1": 0.1, "H2": 0.4, "H0": 0.5}},
        ]
    }
    assert prior_beliefs(report) == {"H1": 0.5, "H0": 0.5, "H2": 0.4}


def test_each_scenario_read_has_its_verdict():
    verdicts = read_verdicts(demo_report(scenario_context()))
    assert verdicts["E1"] == {"H1": "strong-support"}
    assert sorted(verdicts) == ["E1", "E2", "E3"]


def test_no_reads_means_no_verdicts():
    assert read_verdicts({"belief_rounds": [{"evidence": "", "verdicts": {}, "belief": {}}]}) == {}
