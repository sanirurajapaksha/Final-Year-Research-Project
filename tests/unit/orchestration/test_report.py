"""M4 reports use real compression/dispatch, with no providers or execution."""

import json
from copy import deepcopy

import pytest

from argus.orchestration import report


@pytest.fixture
def record():
    return {
        "context": {"failing_services": ["cart"]},
        "rounds": [
            {
                "title": "SIMULATED diagnosis",
                "hypotheses": [{"root_cause": "CART_ADDR missing", "probability": 0.9}],
                "actions": [
                    {
                        "command": "kubectl get pods -n default",
                        "is_write": False,
                        "verdict": None,
                        "execution": {"executed": False, "output": "stub: nothing was run"},
                    },
                    {
                        "command": "kubectl scale deployment cart --replicas=0 -n default",
                        "is_write": True,
                        "verdict": {"decision": "BLOCK", "reason": "minimum replicas"},
                        "execution": None,
                    },
                ],
            }
        ],
    }


def test_report_measures_same_scenario_and_preserves_inputs(record):
    batch = report.load_scenario()
    before = batch.model_copy(deep=True)
    saved = deepcopy(record)
    result = report.build_report(batch, record)
    assert result["records"] == 27
    assert result["original_json_bytes"] == len(json.dumps(batch.records, ensure_ascii=False).encode())
    assert result["tsv_bytes"] == len(result["tsv"].encode())
    assert result["round_trip_exact"]
    assert result["alert_time_preserved"]
    assert batch == before
    assert record == saved
    assert result["actions"][0]["executor_reached"]
    assert result["actions"][1]["M3"] == "BLOCK"
    assert not result["actions"][1]["executor_reached"]
    assert not any(row["executed"] for row in result["actions"])
    json.dumps(result)


def test_report_supports_empty_telemetry(record):
    batch = report.load_scenario().model_copy(update={"records": []})
    result = report.build_report(batch, record)
    assert result["tsv_bytes"] == 0
    assert result["round_trip_exact"]


def test_missing_fixture_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "SCENARIO", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        report.load_scenario()


def test_report_rejects_incomplete_saved_run():
    with pytest.raises(KeyError):
        report.build_report(report.load_scenario(), {})


@pytest.mark.parametrize("outcome", report.OUTCOMES)
def test_scripted_replay_success_and_fallback(record, outcome):
    saved = deepcopy(record)
    result = report.routing_replay(record, outcome=outcome)
    assert result["plan"]["status"] == "optimal"
    assert result["plan"]["assignments"][0]["model_id"] == "fake-primary"
    assert result["tasks"][0]["status"] == "succeeded"
    assert result["attempts"][-1]["status"] == "success"
    assert len(result["attempts"]) == (1 if outcome == "Success" else 2)
    assert result["budget"]["spent_units"] == (2 if outcome == "Success" else 5)
    assert result["budget"]["reserved_units"] == 0
    assert record == saved
    json.dumps(result)


def test_scripted_replay_stops_when_fallback_is_unaffordable(record):
    result = report.routing_replay(record, budget=4)
    assert result["tasks"][0]["status"] == "budget_exhausted"
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["status"] == "timeout"
    assert result["budget"]["spent_units"] == 2


def test_scripted_replay_does_not_call_models_for_infeasible_plan(record):
    result = report.routing_replay(record, budget=1)
    assert result["plan"]["status"] == "infeasible"
    assert result["attempts"] == []
    assert result["budget"]["spent_units"] == 0


def test_scripted_replay_rejects_unknown_outcome(record):
    with pytest.raises(ValueError, match="unknown scripted outcome"):
        report.routing_replay(record, outcome="unknown")
