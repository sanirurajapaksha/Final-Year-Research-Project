import csv
import hashlib
import json
import statistics
from pathlib import Path

import pytest

from argus.orchestration import router_benchmark
from argus.orchestration.router import RoutingPlan

FIXTURE = Path(__file__).resolve().parents[3] / "data/fixtures/m4/routing_synthetic.json"


def test_records_plans_raw_timings_and_source_provenance(tmp_path, capsys):
    output = tmp_path / "run"
    arguments = [
        str(FIXTURE),
        "--output-dir",
        str(output),
        "--budgets",
        "5",
        "9",
        "11",
        "--repetitions",
        "2",
        "--warmups",
        "1",
    ]
    original = FIXTURE.read_bytes()

    assert router_benchmark.main(arguments) == 0

    config = json.loads((output / "config.json").read_text(encoding="utf-8"))
    summaries = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    plans = json.loads((output / "plans.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((output / "timings.csv").read_text(encoding="utf-8").splitlines()))
    assert config["input_sha256"] == hashlib.sha256(original).hexdigest()
    assert config["command"][-len(arguments) :] == arguments
    assert config["budgets"] == [5, 9, 11]
    assert isinstance(config["source_dirty"], bool)
    assert len(config["source_commit"]) == 40
    for name, digest in config["source_snapshot_sha256"].items():
        assert hashlib.sha256((output / "source_snapshot" / name).read_bytes()).hexdigest() == digest
    assert (output / "request.json").read_bytes() == FIXTURE.read_bytes() == original
    assert len(rows) == 12
    assert [row["phase"] for row in rows].count("process_first_call") == 1
    assert plans["budget-5"]["status"] == "infeasible"
    assert plans["budget-9"]["total_estimated_cost_units"] == 8
    assert plans["budget-9"]["total_estimated_quality"] == 175
    assert plans["budget-11"]["total_estimated_quality"] == 188
    for summary in summaries:
        times = [
            float(row["elapsed_ms"])
            for row in rows
            if int(row["budget_units"]) == summary["budget_units"] and row["phase"] == "measured"
        ]
        assert len(times) == summary["measured_repetitions"] == 2
        assert all(time >= 0 for time in times)
        assert summary["median_ms"] == statistics.median(times)

    saved = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    assert router_benchmark.main(arguments) == 2
    assert "already exists" in capsys.readouterr().err
    assert all(path.read_bytes() == data for path, data in saved.items())


def test_default_budget_and_no_warmups(tmp_path):
    output = tmp_path / "run"
    assert (
        router_benchmark.main(
            [str(FIXTURE), "--output-dir", str(output), "--repetitions", "1", "--warmups", "0"]
        )
        == 0
    )
    summaries = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert len(summaries) == 1
    assert summaries[0]["budget_units"] == 9
    assert summaries[0]["measured_repetitions"] == 1


@pytest.mark.parametrize("problem", ["missing", "invalid_json", "invalid_request", "duplicate_budgets"])
def test_invalid_input_creates_no_output(tmp_path, problem):
    source = tmp_path / "request.json"
    output = tmp_path / "run"
    extra = []
    if problem == "invalid_json":
        source.write_text("{", encoding="utf-8")
    elif problem == "invalid_request":
        source.write_text("{}", encoding="utf-8")
    elif problem == "duplicate_budgets":
        source.write_bytes(FIXTURE.read_bytes())
        extra = ["--budgets", "9", "9"]
    assert router_benchmark.main([str(source), "--output-dir", str(output), *extra]) == 2
    assert not output.exists()


@pytest.mark.parametrize(
    "flag,value",
    [("--repetitions", "0"), ("--warmups", "-1"), ("--budgets", "-1"), ("--solver-timeout-ms", "0")],
)
def test_invalid_measurement_parameters_rejected(tmp_path, flag, value):
    with pytest.raises(SystemExit) as error:
        router_benchmark.main([str(FIXTURE), "--output-dir", str(tmp_path / "run"), flag, value])
    assert error.value.code == 2


def test_solver_failure_is_recorded_and_returns_failure_exit_code(tmp_path, monkeypatch):
    output = tmp_path / "run"
    monkeypatch.setattr(
        router_benchmark,
        "route",
        lambda *args, **kwargs: RoutingPlan(status="solver_error", reason="timeout"),
    )
    assert router_benchmark.main([str(FIXTURE), "--output-dir", str(output), "--repetitions", "1"]) == 1
    plans = json.loads((output / "plans.json").read_text(encoding="utf-8"))
    assert plans["budget-9"]["status"] == "solver_error"
    assert plans["budget-9"]["assignments"] == []


def test_nonrepeatable_results_are_not_saved(tmp_path, monkeypatch):
    output = tmp_path / "run"
    results = iter([RoutingPlan(status="infeasible"), RoutingPlan(status="solver_error")])
    monkeypatch.setattr(router_benchmark, "route", lambda *args, **kwargs: next(results))
    assert router_benchmark.main([str(FIXTURE), "--output-dir", str(output), "--repetitions", "1"]) == 2
    assert not output.exists()
