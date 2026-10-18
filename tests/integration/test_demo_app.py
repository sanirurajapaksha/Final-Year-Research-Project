"""The demo web page, driven by Streamlit's own test runner. Skipped without the 'demo' extra."""

import json
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "src" / "argus" / "demo" / "app.py"


def test_page_runs_the_incident_and_shows_the_verdicts(monkeypatch, tmp_path):
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
    assert not app.exception
    assert any("Press" in info.value for info in app.info)

    app.button[0].click().run(timeout=60)
    assert not app.exception
    assert any("M3: BLOCK" in error.value for error in app.error)  # round 1: scale cart to 0
    assert any("M3: APPROVE" in success.value for success in app.success)  # round 2: the fix
