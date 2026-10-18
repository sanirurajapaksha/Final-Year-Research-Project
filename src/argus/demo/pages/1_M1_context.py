"""Dashboard page for M1, System Context (owner: Minidu). PLACEHOLDER until Minidu fills it in.

It shows M1's real output from the run on the first page.
"""

import streamlit as st

from argus.demo.views import the_run

st.title("M1: system context")
st.warning("Placeholder page: Minidu will add the service graph and the kept and pruned signals here.")

record = the_run()
st.subheader("M1's output in this run")
st.json(record["context"])
