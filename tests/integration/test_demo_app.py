"""The dashboard page, driven by Streamlit's own test runner. Skipped without the 'demo' extra."""

import json
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "src" / "argus" / "demo" / "app.py"
CART_ADDR = "Cart can't reach its cache (CART_ADDR missing)"
OUT_OF_MEMORY = "Cart keeps crashing (out of memory)"
DISK_FULL = "Hotel search fails (MongoDB disk full)"


@pytest.fixture
def page(monkeypatch, tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from argus.safety import formulation

    def fake_llm(prompt, schema, model, timeout_s):
        answer = {"kind": "deployment", "name": "cart", "namespace": "default"}
        answer["effect"] = "pod_template_change"
        answer["replicas"] = 0
        return json.dumps(answer), {}

    monkeypatch.setattr(formulation, "complete_json", fake_llm)
    monkeypatch.setenv("ARGUS_M3_LLM_LOG", str(tmp_path / "llm.jsonl"))
    app = AppTest.from_file(str(APP)).run(timeout=60)
    app.sidebar.toggle[0].set_value(False)  # no presenting pauses in tests
    return app


def run_sample(app, name: str):
    app.sidebar.selectbox[0].set_value(name)
    app.sidebar.button[0].click().run(timeout=120)
    assert not app.exception
    return app


def test_before_a_run_the_page_asks_for_an_incident(page):
    assert not page.exception
    assert any("Run the incident" in info.value for info in page.info)


def test_the_cart_addr_incident_ends_with_an_approved_fix(page):
    app = run_sample(page, CART_ADDR)
    assert any("Fix approved by the safety layer" in success.value for success in app.success)
    assert any("Safety layer: APPROVE" in success.value for success in app.success)  # inside its stage


def test_the_out_of_memory_restart_is_blocked_then_the_scale_up_approved(page):
    app = run_sample(page, OUT_OF_MEMORY)
    assert any("Safety layer: BLOCK (z3: sat)" in error.value for error in app.error)
    assert any("Fix approved by the safety layer" in success.value for success in app.success)
    tabs = {tab.label: tab for tab in app.tabs}
    assert {"Belief & Evidence", "Diagnosis Summary", "Fixes"} <= tabs.keys()
    assert len(tabs["Belief & Evidence"].get("vega_lite_chart")) == 2
    assert any("Diagnosis summary" in text.value for text in tabs["Diagnosis Summary"].markdown)
    assert any("Leading hypothesis:" in text.value for text in tabs["Diagnosis Summary"].markdown)
    assert any("Fix 1" in text.value for text in tabs["Fixes"].markdown)


def table_with_columns(app, *columns):
    matches = [table.value for table in app.table if set(columns) == set(table.value.columns)]
    assert len(matches) == 1
    return matches[0]


def test_m4_compression_and_routing_controls(page):
    app = run_sample(page, OUT_OF_MEMORY)
    checks = table_with_columns(app, "check", "passed")
    assert checks["passed"].all()
    compression = app.session_state["stages"][1]["details"]
    assert any(compression["tsv"].strip() == code.value.strip() for code in app.code)
    assert any(button.label == "Download orchestration report" for button in app.get("download_button"))
    assignments = table_with_columns(app, "task_id", "model_id", "estimated_cost_units", "quality", "layer")
    assert assignments.iloc[0]["model_id"] == "fake-primary"
    attempts = table_with_columns(app, "task_id", "model_id", "status", "charged_estimated_units", "reason")
    assert list(attempts["status"]) == ["timeout", "success"]

    app.slider[0].set_value(4).run(timeout=60)
    assert not app.exception
    tasks = table_with_columns(app, "task_id", "status", "reason")
    assert tasks.iloc[0]["status"] == "budget_exhausted"

    app.slider[0].set_value(1).run(timeout=60)
    assert not app.exception
    assert any("infeasible" in text.value for text in app.markdown)
    assert app.warning


@pytest.mark.parametrize("sample", [CART_ADDR, OUT_OF_MEMORY, DISK_FULL])
def test_pipeline_uses_descriptive_names_without_module_numbers(page, sample):
    app = run_sample(page, sample)
    visible = [
        element.value
        for kind in ("markdown", "caption", "success", "error", "info", "warning")
        for element in app.get(kind)
    ]
    visible += [element.label for element in app.get("expander")]
    visible += [element.label for element in app.get("download_button")]
    page_text = "\n".join(visible)
    for label in (
        "Prepare Telemetry",
        "Build Context",
        "Diagnose Cause",
        "Verify Safety",
        "Revise Plan",
        "Execute Action",
    ):
        assert label in page_text
    assert re.search(r"\bM[1-4]\b", page_text) is None


@pytest.mark.parametrize("model_outcome", ["Success", "Invalid output", "Model error"])
def test_m4_replay_other_primary_outcomes(page, model_outcome):
    app = run_sample(page, OUT_OF_MEMORY)
    app.selectbox[0].set_value(model_outcome).run(timeout=60)
    assert not app.exception
    tasks = table_with_columns(app, "task_id", "status", "reason")
    assert tasks.iloc[0]["status"] == "succeeded"


def click(app, label: str):
    for button in app.button:
        if button.label == label:
            return button.click().run(timeout=120)
    raise AssertionError(f"no button {label!r}")


def test_the_verification_stage_draws_the_steps_of_an_example(page):
    app = click(run_sample(page, OUT_OF_MEMORY), "Shell trick")
    assert not app.exception
    assert any("Stopped here" in text.value for text in app.markdown)  # the pre-filter step card
    assert any("pre-filter" in error.value for error in app.error)


def test_the_verification_stage_verifies_a_typed_command_and_shows_the_formula(page):
    app = run_sample(page, OUT_OF_MEMORY)
    app.text_input[0].set_value("kubectl scale deployment cart --replicas=2 -n default")
    app = click(app, "Verify this command")
    assert not app.exception
    assert any("Safety layer: APPROVE (z3: unsat)" in success.value for success in app.success)
    assert any("Z3: unsat" in code.value for code in app.code)  # the formula, read out
