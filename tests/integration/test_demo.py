"""The end-to-end demo: real M4, M1 and M3 on scenario_01, M2 simulated, the LLM a fake."""

import json

from argus.config import Settings
from argus.demo.__main__ import main
from argus.demo.run import KUBECTL_OUTPUT, run_demo, verdict_line
from argus.safety import formulation


def demo_settings(tmp_path) -> Settings:
    return Settings(
        solver_timeout_s=30.0,
        solver_memory_mb=512,
        m3_kubectl_output=str(KUBECTL_OUTPUT),
        llm_model="test/model",
        m3_llm_log=str(tmp_path / "llm.jsonl"),
    )


def write_actions(one_round: dict) -> list[dict]:
    writes = []
    for action in one_round["actions"]:
        if action["is_write"]:
            writes.append(action)
    return writes


def test_risky_restart_is_blocked_and_the_fix_is_approved(monkeypatch, tmp_path):
    def fake_llm(prompt, schema, model, timeout_s):
        answer = {"kind": "deployment", "name": "cart", "namespace": "default"}
        answer["effect"] = "pod_template_change"
        answer["replicas"] = 0
        return json.dumps(answer), {}

    monkeypatch.setattr(formulation, "complete_json", fake_llm)

    record = run_demo(demo_settings(tmp_path))

    round_1, round_2 = record["rounds"]
    risky = write_actions(round_1)[0]
    assert risky["verdict"]["decision"] == "BLOCK"
    assert risky["verdict"]["counterexample"]["after"] == {"replicas": 0}
    assert risky["execution"] is None  # a blocked write never reaches M4's executor

    fix = write_actions(round_2)[0]
    assert fix["verdict"]["decision"] == "APPROVE"
    assert "formulation" in fix["verdict"]["timings_ms"]
    assert fix["execution"] is not None  # approved, so M4's (stub) executor gets it


def test_without_an_llm_key_the_fix_is_blocked(monkeypatch, tmp_path):
    monkeypatch.delenv("ARGUS_LLM_API_KEY", raising=False)
    record = run_demo(demo_settings(tmp_path))
    fix = write_actions(record["rounds"][1])[0]
    assert fix["verdict"]["decision"] == "BLOCK"
    assert fix["verdict"]["reason"].startswith("formulation: LLM:")


def test_main_prints_and_saves_the_run(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ARGUS_LLM_API_KEY", raising=False)
    monkeypatch.setenv("ARGUS_M3_LLM_LOG", str(tmp_path / "llm.jsonl"))
    saved = tmp_path / "run.json"

    assert main(["--save", str(saved)]) == 0

    printed = capsys.readouterr().out
    assert "Round 1" in printed
    assert "M3: BLOCK" in printed
    assert json.loads(saved.read_text(encoding="utf-8"))["telemetry_records"] == 27


def test_verdict_line_leaves_out_z3_when_the_solver_never_ran():
    assert verdict_line({"decision": "BLOCK", "z3_result": "sat"}) == "M3: BLOCK (z3: sat)"
    assert verdict_line({"decision": "BLOCK", "z3_result": None}) == "M3: BLOCK"
