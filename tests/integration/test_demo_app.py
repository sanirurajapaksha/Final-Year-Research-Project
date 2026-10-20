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
