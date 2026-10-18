"""Demo web page: run one incident through the agent and show what each module did.

    python -m streamlit run src/argus/demo/app.py      (from the repo root; needs the 'demo' extra)

Every value on the page comes from run_demo() in run.py, the same run `python -m argus.demo`
prints. M2 is simulated (and says so); nothing is executed on any cluster.
"""

import os

import streamlit as st

from argus.demo.run import demo_settings, run_demo, verdict_line


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
