"""Display helpers shared by the dashboard's pages. Display only: no module logic lives here."""

import streamlit as st

from argus.demo.run import verdict_line


def show_verdict(verdict: dict) -> None:
    """M3's verdict: the decision and reason, the counterexample if any, and the stage timings."""
    text = f"{verdict_line(verdict)}. {verdict['reason']}"
    if verdict["decision"] == "APPROVE":
        st.success(text)
    else:
        st.error(text)
    if verdict["counterexample"] is not None:
        st.markdown("Counterexample (an end state that breaks the rule):")
        st.json(verdict["counterexample"])
    stages = []
    for stage, ms in verdict["timings_ms"].items():
        stages.append(f"{stage} {ms:.1f} ms")
    st.caption("M3 timings: " + ", ".join(stages))


def the_run() -> dict:
    """The run made on the first page. Without one, this page shows a hint and stops."""
    record = st.session_state.get("record")
    if record is None:
        st.info("Run the incident on the first page (**app**) first.")
        st.stop()
    return record
