"""Run from the repository root: python -m streamlit run src/argus/orchestration/dashboard/app.py."""

import json

import streamlit as st

from argus.contracts import TelemetryBatch
from argus.orchestration.dashboard.measurements import DEFAULT_FIXTURE, measure

st.set_page_config(page_title="Argus | Telemetry lab", page_icon="🔭", layout="wide")
st.title("Argus · Telemetry lab")
st.caption("M4 compression → M1 contract validation · Local demo")

with st.sidebar:
    st.header("Telemetry input")
    source = st.radio("Source", ["Sample scenario", "Upload JSON"])
    uploaded = st.file_uploader("TelemetryBatch JSON", type=["json"]) if source == "Upload JSON" else None
    st.caption("Sample: scenario_01 · hand-written synthetic telemetry")
    st.info("Live byte measurements. No model calls or cluster commands.")

if source == "Upload JSON" and uploaded is None:
    st.info("Upload a contract v1 TelemetryBatch JSON file to begin.")
    st.stop()

try:
    raw = uploaded.getvalue() if uploaded is not None else DEFAULT_FIXTURE.read_bytes()
    batch = TelemetryBatch.model_validate_json(raw)
    output = measure(batch)
except (OSError, ValueError) as error:
    st.error(f"Cannot process telemetry: {error}")
    st.stop()

st.caption(f"Source: {batch.source} · Alert time: {batch.alert_time or 'not supplied'}")
cards = st.columns(4)
cards[0].metric("Records", output["records"])
cards[1].metric("Compact JSON", f"{output['compact_json_bytes']:,} B")
cards[2].metric("TSV", f"{output['tsv_bytes']:,} B")
reduction = output["reduction_vs_compact"]
cards[3].metric("Reduction vs compact JSON", f"{reduction:.2f}%" if reduction is not None else "N/A")
st.caption("UTF-8 bytes, records only, no added newline. Negative reduction means TSV is larger.")

records_tab, comparison_tab, tsv_tab, checks_tab = st.tabs(
    ["Explore records", "Compare formats", "TSV & downloads", "Validation"]
)
with records_tab:
    query = st.text_input("Search records", placeholder="Service, message, metric name…")
    groups = st.tabs(["Metrics", "Logs", "Spans", "Kubernetes"])
    for tab, kind in zip(groups, ["metric", "log", "span", "k8s"], strict=True):
        with tab:
            records = [record for record in batch.records if record.get("kind") == kind]
            records = [r for r in records if query.casefold() in json.dumps(r, ensure_ascii=False).casefold()]
            st.caption(f"{len(records)} matching records")
            # Nested values display consistently without Arrow mixed-type errors.
            display = [
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else str(value)
                    if value is not None
                    else "null"
                    for key, value in record.items()
                }
                for record in records
            ]
            if display:
                st.dataframe(display, hide_index=True, width="stretch")
            else:
                st.info("No matching records.")
with comparison_tab:
    st.dataframe(
        [
            {"Format": "Compact JSON (main baseline)", "UTF-8 bytes": output["compact_json_bytes"]},
            {"Format": "Default JSON (includes spaces)", "UTF-8 bytes": output["default_json_bytes"]},
            {"Format": "TSV", "UTF-8 bytes": output["tsv_bytes"]},
        ],
        hide_index=True,
        width="stretch",
    )
    secondary = output["reduction_vs_default"]
    st.write(f"Reduction vs default JSON: {secondary:.2f}%" if secondary is not None else "Reduction: N/A")
    st.caption("Byte size only; this does not measure token savings or generalize beyond this input.")
    with st.expander("Original JSON"):
        st.json(batch.model_dump(mode="json"))
with tsv_tab:
    st.caption("Raw transport format; explore the readable tables in Explore records.")
    st.code(output["tsv"], language="text")
    st.download_button(
        "Download TSV", output["tsv"].encode("utf-8"), "telemetry.tsv", "text/tab-separated-values"
    )
    st.download_button("Download original JSON", raw, "telemetry.json", "application/json")
    summary = {key: value for key, value in output.items() if key != "tsv"}
    st.download_button(
        "Download measurements", json.dumps(summary, indent=2), "measurements.json", "application/json"
    )
with checks_tab:
    for label, passed in output["checks"].items():
        if passed:
            st.success(label)
        else:
            st.error(label)
    st.caption("Records also passed M1 contract validation before compression.")
