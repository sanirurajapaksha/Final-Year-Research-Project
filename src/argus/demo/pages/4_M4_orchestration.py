"""Dashboard page for M4, Orchestration (owner: Nethmi). PLACEHOLDER until Nethmi fills it in.

It shows what M4 did with each action in the run on the first page.
"""

import streamlit as st

from argus.demo.views import the_run

st.title("M4: orchestration")
st.warning("Placeholder page: Nethmi will move the compression, routing and fallback views here.")

record = the_run()
st.metric("Telemetry records compressed for M1", record["telemetry_records"])

st.subheader("What M4 did with each action")
rows = []
for one_round in record["rounds"]:
    for action in one_round["actions"]:
        row = {"round": one_round["title"], "command": action["command"], "kind": "read", "M3": "not asked"}
        if action["is_write"]:
            row["kind"] = "write"
            row["M3"] = action["verdict"]["decision"]
        row["executed"] = False
        if action["execution"] is not None:
            row["executed"] = action["execution"]["executed"]
        rows.append(row)
st.table(rows)
st.caption("The executor is a stub in PP1: nothing runs on any cluster.")
