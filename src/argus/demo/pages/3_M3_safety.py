"""Dashboard page for M3, the safety gate (owner: Saniru).

Checks any command typed in, and shows every M3 check from the run on the first page.
"""

import streamlit as st
from dotenv import load_dotenv

from argus.contracts import ProposedAction
from argus.demo.run import demo_settings
from argus.demo.views import show_verdict
from argus.safety.gate import check

# This page can be opened first, so it loads .env (the LLM key) itself, like the first page.
load_dotenv(".env")

st.title("M3: safety gate")
st.caption(
    "Each write command goes through: pre-filter → cluster facts (saved kubectl output) → the "
    "parser, or the LLM for a patch → Z3 in a sandbox. Z3 is asked about the NEGATED rule: "
    "unsat → APPROVE, sat → BLOCK with a counterexample, anything else → BLOCK."
)

st.subheader("Check a command")
command = st.text_input(
    "A kubectl write command", value="kubectl scale deployment cart --replicas=0 -n default"
)
st.caption(
    "Cluster facts: namespace default (the demo's services). A patch costs one LLM call (team budget)."
)
if st.button("Check with M3"):
    verdict = check(ProposedAction(command=command, is_write=True), settings=demo_settings())
    show_verdict(verdict.model_dump(mode="json"))

st.subheader("M3's checks in this run")
record = st.session_state.get("record")
if record is None:
    st.info("Run the incident on the first page (**app**) to see its checks here.")
else:
    for one_round in record["rounds"]:
        for action in one_round["actions"]:
            if action["verdict"] is not None:
                st.code(action["command"], language="bash")
                show_verdict(action["verdict"])
