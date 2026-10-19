"""The dashboard's module pages, driven by Streamlit's own test runner. Skipped without the 'demo' extra."""

from pathlib import Path

import pytest

PAGES = Path(__file__).resolve().parents[2] / "src" / "argus" / "demo" / "pages"

# A small hand-made run, in the shape run_demo() returns.
RECORD = {
    "incident": "test incident",
    "telemetry_records": 3,
    "context": {"notes": "test notes", "failing_services": ["cart"], "anomalies": ["cart: log_error"]},
    "rounds": [
        {
            "title": "M2 (SIMULATED) proposes",
            "hypotheses": [{"root_cause": "CART_ADDR is missing", "probability": 0.6, "evidence": []}],
            "actions": [
                {
                    "command": "kubectl get pods -n default",
                    "is_write": False,
                    "verdict": None,
                    "execution": None,
                },
                {
                    "command": "kubectl scale deployment cart --replicas=0 -n default",
                    "is_write": True,
                    "verdict": {
                        "command": "kubectl scale deployment cart --replicas=0 -n default",
                        "z3_result": "sat",
                        "decision": "BLOCK",
                        "reason": "counterexample found: violates min_replicas",
                        "violated_invariants": ["min_replicas"],
                        "counterexample": {"before": {"replicas": 1}, "after": {"replicas": 0}},
                        "timings_ms": {"prefilter": 0.1},
                    },
                    "execution": None,
                },
            ],
        }
    ],
}


def page(name: str):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(PAGES / name))


@pytest.mark.parametrize("name", ["1_M1_context.py", "2_M2_diagnosis.py", "4_M4_orchestration.py"])
def test_a_module_page_without_a_run_asks_for_one(name):
    app = page(name).run(timeout=60)
    assert not app.exception
    assert any("Run the incident" in info.value for info in app.info)


@pytest.mark.parametrize("name", ["1_M1_context.py", "2_M2_diagnosis.py", "4_M4_orchestration.py"])
def test_a_module_page_shows_the_run(name):
    app = page(name)
    app.session_state["record"] = RECORD
    app.run(timeout=60)
    assert not app.exception
    assert not app.info


def test_the_m3_page_shows_the_runs_checks():
    app = page("3_M3_safety.py")
    app.session_state["record"] = RECORD
    app.run(timeout=60)
    assert not app.exception
    assert any("M3: BLOCK (z3: sat)" in error.value for error in app.error)


def test_the_m3_page_checks_a_typed_command():
    # A scale needs no LLM: M3 checks it against the saved kubectl output for namespace default.
    app = page("3_M3_safety.py").run(timeout=60)
    app.text_input[0].input("kubectl scale deployment cart --replicas=0 -n default")
    app.button[0].click().run(timeout=60)
    assert not app.exception
    assert any("M3: BLOCK (z3: sat)" in error.value for error in app.error)
