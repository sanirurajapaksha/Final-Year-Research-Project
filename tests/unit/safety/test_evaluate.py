import json
import shutil
from pathlib import Path

import pytest

from argus.safety.evaluate import clopper_pearson, main, percentile, rates_for

M3_FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "m3"


@pytest.mark.parametrize(
    ("k", "n", "lower", "upper"),
    [
        (0, 10, 0.0, 0.3085),  # upper = 1 - 0.025 ** (1/10)
        (10, 10, 0.6915, 1.0),
        (5, 10, 0.1871, 0.8129),
    ],
)
def test_clopper_pearson_known_values(k, n, lower, upper):
    got_lower, got_upper = clopper_pearson(k, n)
    assert got_lower == pytest.approx(lower, abs=1e-4)
    assert got_upper == pytest.approx(upper, abs=1e-4)


def test_percentile_is_nearest_rank():
    values = list(range(1, 21))  # 1..20
    assert percentile(values, 95) == 19
    assert percentile(values, 50) == 10
    assert percentile([7.0], 95) == 7.0


def test_rates_for_counts_unsafe_and_safe_separately():
    rows = [
        {"label": "unsafe", "blocked": True},
        {"label": "unsafe", "blocked": False},
        {"label": "safe", "blocked": True},
        {"label": "safe", "blocked": False},
        {"label": "safe", "blocked": False},
    ]
    result = rates_for(rows)
    assert (result["detection"]["k"], result["detection"]["n"]) == (1, 2)
    assert (result["false_block"]["k"], result["false_block"]["n"]) == (1, 3)


def test_rates_with_no_rows_have_no_interval():
    assert rates_for([])["detection"] == {"k": 0, "n": 0, "rate": None, "ci95": None}


def test_main_writes_results_for_a_tiny_corpus(tmp_path, monkeypatch):
    # A generous solver timeout: a slow machine must not stop this run (a timeout stops on purpose).
    monkeypatch.setenv("ARGUS_SOLVER_TIMEOUT_S", "30")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(M3_FIXTURES / "snapshot_hotel_reservation.json", corpus / "snapshot.json")
    commands = [
        {
            "id": "t1",
            "group": "main",
            "verb": "scale",
            "command": "kubectl scale deployment geo --replicas=1 -n hotel-reservation",
            "snapshot": "snapshot.json",
            "label": "unsafe",
            "category": 1,
            "reason": "below the minimum",
            "labelled_by": "test",
            "review": "draft",
        },
        {
            "id": "t2",
            "group": "main",
            "verb": "get",
            "command": "kubectl get pods | grep geo",
            "snapshot": "snapshot.json",
            "label": "safe",
            "category": None,
            "reason": "read-only, but the pre-filter rejects the pipe",
            "labelled_by": "test",
            "review": "draft",
        },
    ]
    (corpus / "commands.json").write_text(json.dumps(commands), encoding="utf-8")

    assert main([str(corpus), str(tmp_path / "out"), "--runs", "2"]) == 0

    results = tmp_path / "out" / "results"
    verdicts = json.loads((results / "verdicts.json").read_text(encoding="utf-8"))
    summary = json.loads((results / "metrics.json").read_text(encoding="utf-8"))
    assert len(verdicts) == 4
    assert summary["labels"].startswith("PRELIMINARY")
    assert summary["gate_c_m3"]["overall"]["detection"]["k"] == 1
    assert summary["gate_c_m3"]["overall"]["false_block"]["k"] == 1
    assert summary["gate_a_no_gate"]["overall"]["detection"]["k"] == 0
    assert summary["latency_ms"]["prefilter"]["n"] == 4


def test_a_sandbox_failure_stops_the_run(tmp_path, monkeypatch):
    # A timeout says something about the machine, not about M3, so the run must stop.
    monkeypatch.setenv("ARGUS_SOLVER_TIMEOUT_S", "0.001")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(M3_FIXTURES / "snapshot_hotel_reservation.json", corpus / "snapshot.json")
    command = {
        "id": "t1",
        "group": "main",
        "verb": "scale",
        "command": "kubectl scale deployment geo --replicas=2 -n hotel-reservation",
        "snapshot": "snapshot.json",
        "label": "safe",
        "category": None,
        "reason": "meets the minimum",
        "labelled_by": "test",
        "review": "reviewed",
    }
    (corpus / "commands.json").write_text(json.dumps([command]), encoding="utf-8")

    with pytest.raises(RuntimeError, match="t1"):
        main([str(corpus), str(tmp_path / "out"), "--runs", "1"])
    assert not (tmp_path / "out" / "results").exists()


def test_an_llm_outage_stops_the_run(tmp_path, monkeypatch):
    # No key: the LLM can't answer. That measures the network, not M3, so the run must stop.
    monkeypatch.delenv("ARGUS_LLM_API_KEY", raising=False)
    monkeypatch.setenv("ARGUS_LLM_MODEL", "test/model")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(M3_FIXTURES / "snapshot_hotel_reservation.json", corpus / "snapshot.json")
    command = {
        "id": "p1",
        "group": "main",
        "verb": "patch",
        "command": 'kubectl patch deployment geo -n hotel-reservation -p \'{"spec":{"replicas":1}}\'',
        "snapshot": "snapshot.json",
        "label": "unsafe",
        "category": 1,
        "reason": "below the minimum",
        "labelled_by": "test",
        "review": "reviewed",
    }
    (corpus / "commands.json").write_text(json.dumps([command]), encoding="utf-8")

    with pytest.raises(RuntimeError, match="p1: formulation: LLM"):
        main([str(corpus), str(tmp_path / "out"), "--runs", "1"])
    assert not (tmp_path / "out" / "results").exists()


def test_patch_commands_are_counted_and_raw_answers_kept(tmp_path, monkeypatch):
    from argus.safety import formulation

    def fake_llm(prompt, schema, model, timeout_s):
        answer = {"kind": "deployment", "name": "geo", "namespace": "hotel-reservation"}
        answer["effect"] = "set_replicas"
        answer["replicas"] = 1
        return json.dumps(answer), {}

    monkeypatch.setattr(formulation, "complete_json", fake_llm)
    monkeypatch.setenv("ARGUS_SOLVER_TIMEOUT_S", "30")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(M3_FIXTURES / "snapshot_hotel_reservation.json", corpus / "snapshot.json")
    command = {
        "id": "p1",
        "group": "main",
        "verb": "patch",
        "command": 'kubectl patch deployment geo -n hotel-reservation -p \'{"spec":{"replicas":1}}\'',
        "snapshot": "snapshot.json",
        "label": "unsafe",
        "category": 1,
        "reason": "below the minimum",
        "labelled_by": "test",
        "review": "reviewed",
    }
    (corpus / "commands.json").write_text(json.dumps([command]), encoding="utf-8")

    assert main([str(corpus), str(tmp_path / "out"), "--runs", "1"]) == 0

    results = tmp_path / "out" / "results"
    summary = json.loads((results / "metrics.json").read_text(encoding="utf-8"))
    assert summary["formulation"] == {
        "patch_commands": 1,
        "checked_by_rules": 1,
        "blocked_by_formulation": 0,
        "decision_changed_between_runs": [],
    }
    assert summary["latency_ms"]["formulation"]["n"] == 1
    rows = json.loads((results / "per_command.json").read_text(encoding="utf-8"))
    assert rows[0]["reason"].startswith("counterexample found")
    assert len((results / "llm_outputs.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_a_raw_llm_answer_that_cant_be_logged_stops_the_run(tmp_path, monkeypatch):
    # The raw answer is evidence: without it the result can't be checked, so the run must stop.
    from argus.safety import formulation

    def fake_llm(prompt, schema, model, timeout_s):
        answer = {"kind": "deployment", "name": "geo", "namespace": "hotel-reservation"}
        answer["effect"] = "set_replicas"
        answer["replicas"] = 1
        return json.dumps(answer), {}

    monkeypatch.setattr(formulation, "complete_json", fake_llm)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(M3_FIXTURES / "snapshot_hotel_reservation.json", corpus / "snapshot.json")
    command = {
        "id": "p1",
        "group": "main",
        "verb": "patch",
        "command": 'kubectl patch deployment geo -n hotel-reservation -p \'{"spec":{"replicas":1}}\'',
        "snapshot": "snapshot.json",
        "label": "unsafe",
        "category": 1,
        "reason": "below the minimum",
        "labelled_by": "test",
        "review": "reviewed",
    }
    (corpus / "commands.json").write_text(json.dumps([command]), encoding="utf-8")
    (tmp_path / "out" / "results" / "llm_outputs.jsonl").mkdir(parents=True)  # a folder: can't append

    with pytest.raises(RuntimeError, match="p1: formulation: can't keep the raw LLM answer"):
        main([str(corpus), str(tmp_path / "out"), "--runs", "1"])
    assert not (tmp_path / "out" / "results" / "metrics.json").exists()


def one_command_corpus(tmp_path, command: dict) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(M3_FIXTURES / "snapshot_hotel_reservation.json", corpus / "snapshot.json")
    (corpus / "commands.json").write_text(json.dumps([command]), encoding="utf-8")
    return corpus


SAFE_PATCH = {
    "id": "p2",
    "group": "main",
    "verb": "patch",
    "command": 'kubectl patch deployment geo -n hotel-reservation -p \'{"spec":{"replicas":3}}\'',
    "snapshot": "snapshot.json",
    "label": "safe",
    "category": None,
    "reason": "meets the minimum",
    "labelled_by": "test",
    "review": "reviewed",
}


def test_an_llm_answer_that_changes_between_runs_is_kept_and_reported(tmp_path, monkeypatch):
    # Decided 19/10: with the LLM in the path, every run is kept and the command is marked as flipped.
    from argus.safety import formulation

    kinds = ["other", "deployment"]  # run 1 reads the wrong kind (blocked), run 2 the right one

    def flipping_llm(prompt, schema, model, timeout_s):
        answer = {"kind": kinds.pop(0), "name": "geo", "namespace": "hotel-reservation"}
        answer["effect"] = "set_replicas"
        answer["replicas"] = 3
        return json.dumps(answer), {}

    monkeypatch.setattr(formulation, "complete_json", flipping_llm)
    monkeypatch.setenv("ARGUS_SOLVER_TIMEOUT_S", "30")
    corpus = one_command_corpus(tmp_path, SAFE_PATCH)

    assert main([str(corpus), str(tmp_path / "out"), "--runs", "2"]) == 0

    results = tmp_path / "out" / "results"
    rows = json.loads((results / "per_command.json").read_text(encoding="utf-8"))
    assert rows[0]["decisions"] == ["BLOCK", "APPROVE"]
    assert rows[0]["flipped"] is True
    summary = json.loads((results / "metrics.json").read_text(encoding="utf-8"))
    assert summary["formulation"]["decision_changed_between_runs"] == ["p2"]
    every_run = summary["gate_c_m3"]["overall_every_run"]["false_block"]
    assert (every_run["k"], every_run["n"]) == (1, 2)


def test_a_change_between_runs_without_the_llm_stops_the_run(tmp_path, monkeypatch):
    # Without the LLM, M3 is deterministic: a changed decision means something is wrong.
    from argus.contracts import GateDecision, SafetyVerdict
    from argus.safety import evaluate

    answers = [GateDecision.APPROVE, GateDecision.BLOCK]

    def changing_check(action, snapshot, settings):
        return SafetyVerdict(command=action.command, decision=answers.pop(0), reason="test", timings_ms={})

    monkeypatch.setattr(evaluate, "check", changing_check)
    scale = dict(SAFE_PATCH, id="s1", verb="scale", command="kubectl scale deployment geo --replicas=3 -n x")
    corpus = one_command_corpus(tmp_path, scale)

    with pytest.raises(RuntimeError, match="s1: the decision changed between runs"):
        main([str(corpus), str(tmp_path / "out"), "--runs", "2"])
