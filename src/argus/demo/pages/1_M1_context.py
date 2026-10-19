"""Dashboard page for M1, System Context (owner: Minidu). Display only: the data comes from
argus.context.report.report_data().

M1 is re-run here on the same telemetry the first page used, through M4's real compress(), so the
page can show what M1 keeps to itself (the graph and the pruned signals). M1 makes no model calls.
"""

import streamlit as st

from argus.context.report import report_data
from argus.context.service import build_report
from argus.contracts import TelemetryBatch
from argus.demo.run import TELEMETRY
from argus.demo.views import the_run
from argus.orchestration.service import compress

st.title("M1: system context")
record = the_run()

batch = TelemetryBatch.model_validate_json(TELEMETRY.read_text(encoding="utf-8"))
compressed = compress(batch)
data = report_data(build_report(compressed))
st.caption(
    "M1 re-run on the same synthetic scenario_01 telemetry as the first page, "
    "so the graph and the pruned signals can be shown."
)
if data["notes"] != record["context"]["notes"]:
    st.warning("This differs from the first page's run. Run the incident again.")

st.subheader("Input: M4's compressed telemetry")
cards = st.columns(3)
cards[0].metric("Records", data["records"])
cards[1].metric("Compressed TSV bytes", compressed.compressed_size)
cards[2].metric("Stage 1 anomalies", data["stage1_count"])

st.subheader("Service dependency graph (from spans)")
graph = data["graph"]
if graph is None:
    st.info("No graph: M1 ran Stage 1 only.")
else:
    st.table(graph["edges"])
    st.write(f"Failing services: {', '.join(graph['failing_services']) or 'none'}")
    path = ", ".join(graph["failing_path"]) or "none"
    st.write(f"Failing path (failing services and their callers): {path}")
    st.write(f"Entry point: {graph['entry_point'] or 'unknown'}")
    if graph["unseen_callees"]:
        st.write(f"Failed calls with no span from the callee: {graph['unseen_callees']}")

st.subheader(f"Stage 2: kept {data['kept_count']} of {data['stage1_count']} anomalies")
kept = [row for row in data["signals"] if row["kept"]]
pruned = [row for row in data["signals"] if not row["kept"]]
st.write("Kept, sent to M2")
st.table(kept)
st.write("Pruned, not sent to M2")
if pruned:
    st.table(pruned)
else:
    st.caption("Nothing was pruned.")
st.caption(data["notes"])

st.subheader("Output: the Semantic Context Object M2 receives")
st.json(data["context"], expanded=False)
