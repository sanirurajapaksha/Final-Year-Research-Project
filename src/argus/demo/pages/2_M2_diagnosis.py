"""Dashboard page for M2, Diagnosis (owner: Kaveen). PLACEHOLDER until Kaveen fills it in.

M2 is SIMULATED in this demo (src/argus/demo/scenario.py) until M2's diagnose() is ready.
"""

import streamlit as st

from argus.demo.views import the_run

st.title("M2: diagnosis")
st.warning(
    "M2 is SIMULATED in this demo until Kaveen's diagnose() is ready. "
    "Kaveen will add the hypotheses, beliefs per round and the reads here."
)

record = the_run()
for number, one_round in enumerate(record["rounds"], start=1):
    st.subheader(f"Round {number}: {one_round['title']}")
    st.table(one_round["hypotheses"])
