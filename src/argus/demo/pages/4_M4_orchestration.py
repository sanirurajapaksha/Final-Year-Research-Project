"""M4's display page in the shared PP1 app (owner: Nethmi Herath)."""

import json

import streamlit as st

from argus.demo.views import the_run
from argus.orchestration.report import OUTCOMES, build_report, load_scenario, routing_replay

st.title("M4: orchestration")
record = the_run()
report = build_report(load_scenario(), record)
# Keep this member's demo and download focused on compression and routing.
compression_report = {key: value for key, value in report.items() if key != "actions"}

st.subheader("Compression: scenario_01 input")
st.caption("Recomputed from the same synthetic telemetry fixture as the incident run.")
cards = st.columns(3)
cards[0].metric("Original JSON bytes", report["original_json_bytes"])
cards[1].metric("Compressed TSV bytes", report["tsv_bytes"])
cards[2].metric("Size reduction", f"{report['reduction_percent']:.1f}%")
st.write(f"{report['records']} records; compact JSON baseline: {report['compact_json_bytes']} bytes.")
st.caption("UTF-8 payload sizes; these are byte measurements, not token counts or API cost savings.")
st.table(
    [
        {"check": "Exact round trip: values, types and order", "passed": report["round_trip_exact"]},
        {"check": "Alert time preserved", "passed": report["alert_time_preserved"]},
    ]
)
with st.expander("Compressed input passed to M1"):
    st.code(report["tsv"], language="text")


st.subheader("Routing and fallback: offline scripted replay")
st.caption(
    "The incident run currently calls M2 directly. This separate experiment replays its first diagnosis "
    "with the real M4 router and dispatcher. Model responses and deadlines are simulated; "
    "no provider calls or actions run. Quality scores and credits are synthetic."
)
budget = st.slider("Attempt budget (synthetic credits)", 0, 10, 5)
outcome = st.selectbox("Primary model outcome", OUTCOMES, index=1)
st.caption("Primary costs 2 credits; fallback costs 3. Failed attempts also consume their estimate.")
replay = routing_replay(record, budget=budget, outcome=outcome)
st.write(f"Routing plan: {replay['plan']['status']}")
if replay["plan"]["status"] == "optimal":
    st.table(replay["plan"]["assignments"])
else:
    st.warning(replay["plan"]["reason"])
st.write("Fallback attempts")
st.table(replay["attempts"])
st.table(replay["tasks"])
st.json(replay["budget"])
with st.expander("Routing request and fallback policy"):
    st.json({"request": replay["request"], "policy": replay["policy"]})
st.download_button(
    "Download M4 report",
    json.dumps({"compression": compression_report, "routing_replay": replay}, ensure_ascii=False, indent=2),
    "m4-report.json",
    "application/json",
)
