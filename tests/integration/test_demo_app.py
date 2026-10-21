"""The dashboard page, driven by Streamlit's own test runner. Skipped without the 'demo' extra."""

import json
from pathlib import Path

import pytest

from argus.demo.flow import SCENARIOS

APP = Path(__file__).resolve().parents[2] / "src" / "argus" / "demo" / "app.py"
CART_ADDR, OUT_OF_MEMORY = list(SCENARIOS)


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
    assert any("Fix approved by M3" in success.value for success in app.success)
    assert any("M3: APPROVE" in success.value for success in app.success)  # inside the M3 stage


def test_the_out_of_memory_incident_ends_with_a_block_and_a_human(page):
    app = run_sample(page, OUT_OF_MEMORY)
    assert any("M3 blocked the fix" in error.value for error in app.error)
    assert any("M3: BLOCK (z3: sat)" in error.value for error in app.error)


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
    assert any(button.label == "Download M4 report" for button in app.get("download_button"))
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


def test_inside_m3_draws_its_steps_for_an_example(page):
    app = click(page, "Shell trick")
    assert not app.exception
    assert any("Stopped here" in text.value for text in app.markdown)  # the pre-filter step card
    assert any("pre-filter" in error.value for error in app.error)


def test_inside_m3_verifies_a_typed_command_and_shows_the_formula(page):
    page.text_input[0].set_value("kubectl scale deployment cart --replicas=2 -n default")
    app = click(page, "Verify with M3")
    assert not app.exception
    assert any("M3: APPROVE (z3: unsat)" in success.value for success in app.success)
    assert any("Z3: unsat" in code.value for code in app.code)  # the formula, read out
