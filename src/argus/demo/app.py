"""The team dashboard's first page: run one incident through the agent and show every step.

    python -m streamlit run src/argus/demo/app.py      (from the repo root; needs the 'demo' extra)

Every value on the page comes from run_demo() in run.py, the same run `python -m argus.demo`
prints. M2 is simulated (and says so); nothing is executed on any cluster.
The other pages, one per module, are in pages/ and show the same run in more detail.
"""

import os

import streamlit as st
from dotenv import load_dotenv

from argus.demo.run import demo_settings, run_demo
from argus.demo.views import show_verdict

# Settings and the LLM key from .env in the folder the page is started from (the repo root).
# Variables already set in the shell win over .env.
load_dotenv(".env")


def show_action(action: dict) -> None:
    """One proposed command, with M3's verdict and M4's result."""
    kind = "Write"
    if not action["is_write"]:
        kind = "Read"
    st.markdown(f"**{kind} proposed by M2**")
    st.code(action["command"], language="bash")

    verdict = action["verdict"]
    if verdict is None:
        st.caption("A read action: M4 runs it without asking M3.")
    else:
        show_verdict(verdict)

    execution = action["execution"]
    if execution is not None:
        st.caption(f"M4 executor: {execution['output']}")


st.set_page_config(page_title="Argus demo", layout="wide")
st.title("Argus: one incident, end to end")
st.caption("M4 → M1 → M2 (simulated) → M4 → M3 safety gate → M4. Saved cluster data; nothing is executed.")

with st.sidebar:
    st.header("Setup")
    if os.environ.get("ARGUS_LLM_API_KEY"):
        st.success("LLM key is set: M3 can read patch commands.")
    else:
        st.warning("No LLM key: M3 will block patch commands (fail-closed).")
    st.caption(f"Cluster facts: saved kubectl output ({demo_settings().m3_kubectl_output}).")
    st.caption("M2 is simulated until M2's diagnose() is ready.")
    st.caption("The pages below show each module's part of the same run.")

if st.button("Run the incident", type="primary"):
    with st.spinner("Running the agent..."):
        st.session_state["record"] = run_demo(demo_settings())

record = st.session_state.get("record")
if record is None:
    st.info("Press **Run the incident** to start.")
    st.stop()

st.subheader("Incident")
st.write(record["incident"])
left, right = st.columns(2)
left.metric("Telemetry records (M4)", record["telemetry_records"])
right.metric("Anomalies flagged (M1)", len(record["context"]["anomalies"]))
with st.expander("What M1 flagged"):
    st.caption(record["context"]["notes"])
    for anomaly in record["context"]["anomalies"]:
        st.write(anomaly)

for number, one_round in enumerate(record["rounds"], start=1):
    st.subheader(f"Round {number}: {one_round['title']}")
    for hypothesis in one_round["hypotheses"]:
        st.write(f"Hypothesis ({hypothesis['probability']:.2f}): {hypothesis['root_cause']}")
    for action in one_round["actions"]:
        show_action(action)
