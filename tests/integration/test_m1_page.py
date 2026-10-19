"""M1's dashboard page, driven by Streamlit's own test runner. Skipped without the 'demo' extra."""

from pathlib import Path

import pytest

from argus.demo.run import demo_settings, run_demo

PAGE = Path(__file__).resolve().parents[2] / "src" / "argus" / "demo" / "pages" / "1_M1_context.py"


def m1_page():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(PAGE))


def test_m1_page_shows_the_graph_and_kept_and_pruned_signals(monkeypatch):
    monkeypatch.delenv("ARGUS_LLM_API_KEY", raising=False)  # no LLM call: M3 blocks the patch
    app = m1_page()
    app.session_state["record"] = run_demo(demo_settings())
    app.run(timeout=60)

    assert not app.exception
    assert not app.warning  # same run as the first page
    edges, kept, pruned = (table.value for table in app.table)
    assert list(zip(edges["caller"], edges["callee"], edges["on_failing_path"], strict=True)) == [
        ("frontend", "cart", True),
        ("frontend", "product-catalog", False),
    ]
    assert sorted(kept["service"]) == ["cart", "cart", "cart", "frontend", "frontend"]
    assert sorted(zip(pruned["service"], pruned["reason"], strict=True)) == [
        ("metrics-server", "not in the call graph"),
        ("metrics-server", "not in the call graph"),
        ("product-catalog", "in the call graph but not on the failing path"),
    ]
    assert any("Stage 2: kept 5 of 8" in header.value for header in app.subheader)
    assert '"frontend" -> "cart"' in app.get("graphviz_chart")[0].proto.spec
    assert [metric.value for metric in app.metric][3:] == ["frontend", "cart, frontend", "cart, frontend"]


def test_m1_page_warns_when_the_first_pages_run_differs():
    app = m1_page()
    app.session_state["record"] = {"context": {"notes": "an older run"}}
    app.run(timeout=60)
    assert not app.exception
    assert any("differs from the first page" in warning.value for warning in app.warning)
