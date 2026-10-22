"""The end-to-end demo flow: all four real modules on the sample incidents, the LLM a fake."""

import json

import pytest

from argus.config import Settings
from argus.demo.__main__ import main
from argus.demo.flow import SCENARIOS, STAGES, VERIFY, load_telemetry, namespace_of, outcome, run_flow
from argus.demo.run import KUBECTL_OUTPUT, verdict_line
from argus.orchestration.report import compression_report
from argus.safety import formulation

CART_ADDR, OUT_OF_MEMORY, DISK_FULL = list(SCENARIOS)


def demo_settings(tmp_path) -> Settings:
    return Settings(
        solver_timeout_s=30.0,
        solver_memory_mb=512,
        m3_kubectl_output=str(KUBECTL_OUTPUT),
        llm_model="test/model",
        m3_llm_log=str(tmp_path / "llm.jsonl"),
    )


@pytest.fixture
def fake_llm(monkeypatch):
    """The LLM reads scenario 1's patch as a pod-template change of cart (no network)."""

    def answer(prompt, schema, model, timeout_s):
        reply = {"kind": "deployment", "name": "cart", "namespace": "default"}
        reply["effect"] = "pod_template_change"
        reply["replicas"] = 0
        return json.dumps(reply), {}

    monkeypatch.setattr(formulation, "complete_json", answer)


def run(name: str, tmp_path) -> dict:
    """Run a sample incident; return its stages by name."""
    text = SCENARIOS[name]["telemetry"].read_text(encoding="utf-8")
    stages = {}
    for stage in run_flow(load_telemetry(text), demo_settings(tmp_path)):
        stages[stage["name"]] = stage
    return stages


def test_stages_come_in_pipeline_order(fake_llm, tmp_path):
    text = SCENARIOS[CART_ADDR]["telemetry"].read_text(encoding="utf-8")
    names = [stage["name"] for stage in run_flow(load_telemetry(text), demo_settings(tmp_path))]
    assert names == STAGES


@pytest.mark.parametrize("sample", list(SCENARIOS))
def test_m4_compression_report_uses_the_incident_payload(sample, tmp_path):
    batch = load_telemetry(SCENARIOS[sample]["telemetry"].read_text(encoding="utf-8"))
    # An edited upload must be measured instead of silently reporting scenario_01.
    batch.records.append({"kind": "log", "service": "uploaded", "message": "custom telemetry"})
    flow = run_flow(batch, demo_settings(tmp_path))
    next(flow)  # telemetry
    details = next(flow)["details"]
    expected = compression_report(batch)
    assert {key: details[key] for key in expected} == expected
    assert details["round_trip_exact"]
    assert details["alert_time_preserved"]


def test_missing_cart_addr_is_diagnosed_and_the_fix_is_approved(fake_llm, tmp_path):
    stages = run(CART_ADDR, tmp_path)
    m1 = stages["M1 · Context"]["details"]
    assert m1["kept_count"] == 5
    assert m1["nrr"] == {"raw": 21, "stage1": 1 - 8 / 21, "stage2": 1 - 5 / 21}
    assert m1["compute_ms"] > 0
    assert m1["context"]["failing_services"] == ["cart", "frontend"]
    assert stages["M2 · Diagnose"]["status"] == "passed"
    check = stages[VERIFY]["details"]["checks"][-1]
    assert check["command"].startswith("kubectl patch deployment cart -n default")
    assert check["verdict"]["decision"] == "APPROVE"
    assert check["execution"] is not None  # approved, so M4's (stub) executor gets it
    assert stages["M2 · Feedback"]["status"] == "skipped"
    assert outcome(list(stages.values()))["kind"] == "approved"


def test_unsafe_restart_is_blocked_and_handed_to_a_human(tmp_path):
    stages = run(OUT_OF_MEMORY, tmp_path)
    check = stages[VERIFY]["details"]["checks"][-1]
    assert check["command"] == "kubectl rollout restart deployment/cart -n shop"
    assert check["verdict"]["decision"] == "BLOCK"
    assert check["verdict"]["counterexample"]["during"] == {"pods_down": 1, "available": 1}
    assert check["execution"] is None  # a blocked write never reaches M4's executor
    assert stages["M2 · Feedback"]["status"] == "attention"  # M2 knows no other safe fix
    assert stages["M4 · Execute"]["status"] == "attention"
    result = outcome(list(stages.values()))
    assert result["kind"] == "blocked"
    assert result["text"] == "During the restart 1 of 2 pods would be down, leaving 1; the minimum is 2."


def test_full_mongodb_volume_is_confirmed_and_handed_to_a_human_with_the_expansion(tmp_path):
    stages = run(DISK_FULL, tmp_path)
    m2 = stages["M2 · Diagnose"]["details"]
    # mongodb-geo sends no spans, but it crash-loops and geo's error names it, so it is the origin.
    assert m2["candidates"][0] == {"service": "mongodb-geo", "weight": 1.5, "role": "origin", "hops": 0}
    top = m2["hypotheses"][0]
    assert (top["component"], top["layer"]) == ("mongodb-geo", "storage")
    assert m2["stop_reason"] == "confident"
    assert "kubectl patch pvc geo-pvc -n hotel-reservation" in m2["report_text"]
    assert '"storage":"2Gi"' in m2["report_text"]
    assert stages[VERIFY]["status"] == "skipped"  # no write: M3 can't check a PVC patch
    assert outcome(list(stages.values()))["kind"] == "handoff"


def test_without_canned_reads_m2_proposes_no_fix_and_m3_has_nothing_to_check(tmp_path):
    batch = json.loads(SCENARIOS[CART_ADDR]["telemetry"].read_text(encoding="utf-8"))
    for record in batch["records"]:
        if record.get("namespace") == "default":
            record["namespace"] = "elsewhere"  # no canned reads exist for this namespace
    stages = {}
    for stage in run_flow(load_telemetry(json.dumps(batch)), demo_settings(tmp_path)):
        stages[stage["name"]] = stage
    assert stages["M2 · Diagnose"]["status"] == "attention"
    assert stages[VERIFY]["status"] == "skipped"
    assert outcome(list(stages.values()))["kind"] == "unsure"


def test_the_namespace_comes_from_the_kubernetes_records():
    batch = load_telemetry(SCENARIOS[OUT_OF_MEMORY]["telemetry"].read_text(encoding="utf-8"))
    assert namespace_of(batch) == "shop"  # kube-system records are left out
    assert (
        namespace_of(load_telemetry('{"source": "x", "collected_at": "2026-10-12T14:20:30Z"}')) == "default"
    )


def test_a_file_that_is_not_telemetry_is_refused():
    with pytest.raises(ValueError):
        load_telemetry('{"records": "not a list"}')


def test_main_prints_every_stage_and_saves_the_run(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ARGUS_M3_LLM_LOG", str(tmp_path / "llm.jsonl"))
    saved = tmp_path / "run.json"

    assert main(["--scenario", "2", "--save", str(saved)]) == 0

    printed = capsys.readouterr().out
    for name in STAGES:
        assert name in printed
    assert "The safety layer blocked the fix" in printed
    assert len(json.loads(saved.read_text(encoding="utf-8"))) == len(STAGES)


def test_verdict_line_leaves_out_z3_when_the_solver_never_ran():
    assert verdict_line({"decision": "BLOCK", "z3_result": "sat"}) == "Safety layer: BLOCK (z3: sat)"
    assert verdict_line({"decision": "BLOCK", "z3_result": None}) == "Safety layer: BLOCK"
