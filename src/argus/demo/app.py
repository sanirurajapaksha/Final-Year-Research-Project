"""Argus dashboard: one incident through the whole agent, drawn as a pipeline (like a CI run).

    python -m streamlit run src/argus/demo/app.py      (from the repo root; needs the 'demo' extra)

Choose a sample incident or upload a telemetry file, then press Run. Each stage card fills in as
its module finishes; open a stage under the pipeline to see how that module decided. The run
itself is in flow.py and the modules; this page only draws it.
"""

import html
import json
import os
import time

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from argus.context.report import graph_dot
from argus.contracts import ProposedAction
from argus.demo.flow import SCENARIOS, STAGES, load_telemetry, outcome, routing_record, run_flow
from argus.demo.run import demo_settings
from argus.demo.views import show_verdict
from argus.diagnosis.core.belief import H0
from argus.diagnosis.demo import prior_beliefs
from argus.orchestration.report import OUTCOMES, routing_replay
from argus.safety.gate import check

# Settings and the LLM key from .env in the folder the page is started from (the repo root).
load_dotenv(".env")

PACE_S = 0.8  # pause after each stage when presenting, so the audience can follow; not in the timings
LABELS = {
    "waiting": "Waiting",
    "running": "Running…",
    "passed": "Passed",
    "blocked": "Blocked",
    "attention": "Needs a human",
    "skipped": "Skipped",
    "failed": "Failed",
}
STYLE = """<style>
.stage {border: 1px solid; border-radius: 10px; padding: 10px 12px; min-height: 150px;}
.stage .name {font-size: 0.8rem; font-weight: 600; opacity: 0.85;}
.stage .state {font-size: 1.05rem; font-weight: 700; margin: 4px 0 6px;}
.stage .line {font-size: 0.8rem; line-height: 1.3;}
.stage .ms {font-size: 0.75rem; opacity: 0.7; margin-top: 6px;}
.waiting, .skipped {border-color: #c9c9c9; background: #f4f4f4; color: #6b6b6b;}
.running {border-color: #2563eb; background: #eff6ff; color: #1e3a8a;}
.passed {border-color: #16a34a; background: #f0fdf4; color: #14532d;}
.blocked, .failed {border-color: #dc2626; background: #fef2f2; color: #7f1d1d;}
.attention {border-color: #d97706; background: #fffbeb; color: #78350f;}
</style>"""


def card(name: str, status: str, line: str, ms: float | None) -> str:
    """One stage card in the pipeline strip (HTML)."""
    if len(line) > 90:
        line = line[:87] + "…"
    timing = ""
    if ms is not None:
        timing = f"{ms:.0f} ms"
    return (
        f'<div class="stage {status}"><div class="name">{html.escape(name)}</div>'
        f'<div class="state">{LABELS[status]}</div><div class="line">{html.escape(line)}</div>'
        f'<div class="ms">{timing}</div></div>'
    )


def run_live(text: str, placeholders: list, present: bool) -> list[dict] | None:
    """Run the incident, filling in each stage card as its module finishes."""
    try:
        batch = load_telemetry(text)
    except ValueError as exc:
        st.error(f"That file is not a telemetry batch (contract v1): {str(exc).splitlines()[0]}")
        return None
    stages = []
    flow = run_flow(batch, demo_settings())
    for index, name in enumerate(STAGES):
        placeholders[index].markdown(card(name, "running", "working…", None), unsafe_allow_html=True)
        try:
            stage = next(flow)
        except Exception as exc:  # show where the run broke instead of a stack trace
            placeholders[index].markdown(card(name, "failed", str(exc), None), unsafe_allow_html=True)
            st.error(f"{name} failed: {type(exc).__name__}: {exc}")
            return None
        stages.append(stage)
        placeholders[index].markdown(
            card(name, stage["status"], stage["headline"], stage["ms"]), unsafe_allow_html=True
        )
        if present:
            time.sleep(PACE_S)
    return stages


def show_outcome(stages: list[dict]) -> None:
    result = outcome(stages)
    text = f"**{result['title']}**"
    if result["command"]:
        text += f"\n\n`{result['command']}`"
    text += f"\n\n{result['text']}"
    if result["kind"] == "approved":
        st.success(text + "\n\nNothing was executed: the executor is a stub in PP1.")
    elif result["kind"] == "blocked":
        st.error(text)
    else:
        st.warning(text)


def show_telemetry(details: dict) -> None:
    st.write(f"Source: {details['source']}")
    st.write(f"Alert time: {details['alert_time']} · namespace: `{details['namespace']}`")
    columns = st.columns(len(details["kinds"]))
    for column, (kind, count) in zip(columns, details["kinds"].items(), strict=True):
        column.metric(f"{kind} records", count)


def show_compress(details: dict) -> None:
    left, middle, right = st.columns(3)
    left.metric("Original JSON", f"{details['original_bytes']} B")
    middle.metric("Compressed TSV", f"{details['compressed_bytes']} B")
    right.metric("Smaller by", f"{details['saved_percent']:.0f}%")
    st.write(f"{details['records']} records; compact JSON baseline: {details['compact_json_bytes']} bytes.")
    st.caption("UTF-8 payload sizes; these are byte measurements, not token counts or API cost savings.")
    st.table(
        [
            {"check": "Exact round trip: values, types and order", "passed": details["round_trip_exact"]},
            {"check": "Alert time preserved", "passed": details["alert_time_preserved"]},
        ]
    )
    with st.expander("Compressed input passed to M1"):
        st.code(details["tsv"], language="text")


def show_context(details: dict) -> None:
    graph = details["graph"]
    if graph is None:
        st.info("No traces in the window, so M1 ran its noise filter only (no service graph).")
    else:
        left, right = st.columns([3, 2])
        left.graphviz_chart(graph_dot(details))
        right.markdown(
            f"**Entry point:** {graph['entry_point'] or 'unknown'}\n\n"
            f"**Failing:** {', '.join(graph['failing_services']) or 'none'}\n\n"
            f"**On the failing path:** {', '.join(graph['failing_path']) or 'none'}\n\n"
            "Red = failing (error spans), orange = healthy caller on the failing path, "
            "grey = off the failing path (its signals are pruned)."
        )
    rows = []
    for signal in details["signals"]:
        kept = "kept" if signal["kept"] else "pruned"
        rows.append(
            {"": kept, "service": signal["service"], "signal": signal["name"], "why": signal["reason"]}
        )
    st.dataframe(rows, hide_index=True)
    st.caption(details["notes"])


def show_diagnosis(details: dict) -> None:
    hypotheses = details["hypotheses"]
    left, middle, right = st.columns(3)
    if hypotheses:
        left.metric("Top hypothesis", f"{hypotheses[0]['component']} [{hypotheses[0]['layer']}]")
        middle.metric("Belief", f"{hypotheses[0]['probability']:.0%}")
    right.metric("Stopped because", details["stop_reason"])

    priors = prior_beliefs(details)
    rows = []
    for hypothesis in hypotheses:
        prior = priors.get(hypothesis["id"], 0.0)
        rows.append(
            {
                "id": hypothesis["id"],
                "hypothesis": f"{hypothesis['component']}: {hypothesis['fault']}",
                "prior → final": f"{prior:.0%} → {hypothesis['probability']:.0%}",
                "status": hypothesis["status"],
            }
        )
    st.dataframe(rows, hide_index=True)

    beliefs = []
    steps = []
    for one_round in details["belief_rounds"]:
        beliefs.append(one_round["belief"])
        steps.append(one_round["step"])
    chart = pd.DataFrame(beliefs, index=pd.Index(steps, name="step")).rename(
        columns={H0: "H0 (none of these)"}
    )
    st.caption("Belief in each hypothesis after every read (H0 = none of them):")
    st.line_chart(chart)

    st.caption("Reads M2 ran to test them (FAKE: canned kubectl output, there is no cluster):")
    for read in details["reads"]:
        result = "ok" if read["ok"] else "unavailable"
        st.markdown(f"**{read['id']}** tests {read['hypothesis']}: `{read['command']}` ({result})")
        st.code(read["output"][:800], language="text")

    st.caption("What M2 proposes:")
    for action in details["diagnosis"]["actions"]:
        kind = "WRITE (goes to M3)" if action["is_write"] else "READ"
        st.markdown(f"**{kind}**: `{action['command']}`")
    if details["diagnosis"]["hypotheses"]:
        for line in details["diagnosis"]["hypotheses"][0]["evidence"]:
            if line.startswith("No write:"):
                st.markdown(line)


def show_checks(checks: list[dict]) -> None:
    writes = [row for row in checks if row["is_write"]]
    if not writes:
        st.caption("No write was proposed, so there was nothing for M3 to check.")
    for row in writes:
        st.code(row["command"], language="bash")
        show_verdict(row["verdict"])


def show_verify(details: dict) -> None:
    st.caption(
        "M3 asks Z3 whether ANY end state of the command breaks a rule: unsat → APPROVE; "
        "sat → BLOCK with that end state as the counterexample; an error or unknown → BLOCK."
    )
    show_checks(details["checks"])
    if details["facts"]:
        st.caption("What M3 knew about the cluster (saved kubectl output, read-only):")
        st.dataframe(details["facts"], hide_index=True)


def show_feedback(details: dict | None) -> None:
    if details is None:
        st.caption("Nothing was blocked, so M2 was not asked again.")
        return
    st.caption("M4 handed M3's BLOCK, with its counterexample, back to M2. M2's answer:")
    if details["diagnosis"]["hypotheses"]:
        for line in details["diagnosis"]["hypotheses"][0]["evidence"]:
            if line.startswith("M3 blocked"):
                st.markdown(line)
    for action in details["diagnosis"]["actions"]:
        kind = "WRITE (goes to M3)" if action["is_write"] else "READ"
        st.markdown(f"**{kind}**: `{action['command']}`")
    show_checks(details["checks"])


def show_execute(details: dict) -> None:
    rows = []
    for row in details["actions"]:
        decision = "not needed (read)"
        if row["verdict"] is not None:
            decision = row["verdict"]["decision"]
        output = "not sent (blocked)"
        if row["execution"] is not None:
            output = row["execution"]["output"]
        rows.append({"command": row["command"], "M3": decision, "executor": output})
    st.dataframe(rows, hide_index=True)
    st.caption(
        "Reads skip M3; a write reaches the executor only with APPROVE. The executor is a stub in PP1."
    )


RENDERERS = {
    "Telemetry": show_telemetry,
    "M4 · Compress": show_compress,
    "M1 · Context": show_context,
    "M2 · Diagnose": show_diagnosis,
    "M3 · Verify": show_verify,
    "M2 · Feedback": show_feedback,
    "M4 · Execute": show_execute,
}


st.set_page_config(page_title="Argus", layout="wide")
st.markdown(STYLE, unsafe_allow_html=True)

with st.sidebar:
    st.header("Incident")
    source = st.radio("Telemetry from", ["Sample incident", "Upload a file"])
    label = None
    text = None
    if source == "Sample incident":
        label = st.selectbox("Sample", list(SCENARIOS))
        text = SCENARIOS[label]["telemetry"].read_text(encoding="utf-8")
        st.download_button(
            "Download its telemetry", text, file_name="telemetry.json", mime="application/json"
        )
        st.caption("Edit the file and upload it to try a variant.")
    else:
        uploaded = st.file_uploader("Telemetry batch (JSON, contract v1)", type="json")
        if uploaded is not None:
            label = uploaded.name
            text = uploaded.getvalue().decode("utf-8")
    present = st.toggle("Step through slowly (for presenting)", value=True)
    run = st.button("Run the incident", type="primary", disabled=text is None)

    st.divider()
    st.subheader("Real or simulated")
    st.markdown(
        "**Real:** the code of all four modules, Z3, and the LLM call that reads a patch.\n\n"
        "**Simulated (no cluster in PP1):** the telemetry (synthetic or uploaded), the results of "
        "M2's reads (canned kubectl output), M3's cluster facts (saved kubectl output), and the "
        "executor (a stub: nothing is run)."
    )
    if os.environ.get("ARGUS_LLM_API_KEY"):
        st.caption(f"LLM: {demo_settings().llm_model} (key set). At most one call per run.")
    else:
        st.caption("No LLM key: M3 blocks patch commands (fail-closed).")

st.title("Argus · incident run")
st.caption(
    "Telemetry goes in; each module runs in turn; every write is checked by M3 before anything "
    "could run; the incident ends with an approved fix or a hand-over to a human."
)

placeholders = []
for column in st.columns(len(STAGES)):
    placeholders.append(column.empty())

if run:
    stages = run_live(text, placeholders, present)
    st.session_state["stages"] = stages
    st.session_state["incident"] = label
stages = st.session_state.get("stages")

if not stages:
    for index, name in enumerate(STAGES):
        placeholders[index].markdown(card(name, "waiting", "", None), unsafe_allow_html=True)
    st.info("Choose an incident in the sidebar and press **Run the incident**.")
    st.stop()

for index, stage in enumerate(stages):
    placeholders[index].markdown(
        card(stage["name"], stage["status"], stage["headline"], stage["ms"]), unsafe_allow_html=True
    )
if not run:
    st.caption(f"Showing the last run: {st.session_state.get('incident')}")
show_outcome(stages)

st.subheader("How each module decided")
for stage in stages:
    with st.expander(f"{stage['name']} · {LABELS[stage['status']]} · {stage['headline']}"):
        RENDERERS[stage["name"]](stage["details"])

st.subheader("Try it yourself")
with st.expander("Check any command against M3"):
    command = st.text_input(
        "A kubectl write command", value="kubectl scale deployment cart --replicas=0 -n default"
    )
    st.caption(
        "Saved cluster facts exist for the namespaces default, shop, hotel-reservation and kube-system. "
        "A patch costs one LLM call (team budget)."
    )
    if st.button("Check with M3"):
        verdict = check(ProposedAction(command=command, is_write=True), settings=demo_settings())
        show_verdict(verdict.model_dump(mode="json"))

with st.expander("M4 model routing: offline replay of this run's diagnosis (not part of the run)"):
    st.caption(
        "The run calls M2 directly. This replays M2's diagnosis through M4's real router and fallback "
        "dispatcher with scripted model answers and invented costs; no model is called."
    )
    left, right = st.columns(2)
    budget = left.slider("Budget (synthetic credits)", 0, 10, 5)
    model_outcome = right.selectbox("Primary model", OUTCOMES, index=1)
    replay = routing_replay(routing_record(stages), budget=budget, outcome=model_outcome)
    st.write(f"Routing plan: {replay['plan']['status']}")
    if replay["plan"]["status"] == "optimal":
        st.table(replay["plan"]["assignments"])
    else:
        st.warning(replay["plan"]["reason"])
    st.write("Fallback attempts")
    st.table(replay["attempts"])
    st.write("Task outcomes")
    st.table(replay["tasks"])
    st.write("Budget accounting (synthetic credits)")
    st.json(replay["budget"])
    st.caption("Primary costs 2 credits, fallback 3; a failed attempt still spends its estimate.")
    with st.expander("Routing request and fallback policy"):
        st.json({"request": replay["request"], "policy": replay["policy"]})
    compression = stages[STAGES.index("M4 · Compress")]["details"]
    st.download_button(
        "Download M4 report",
        json.dumps({"compression": compression, "routing_replay": replay}, ensure_ascii=False, indent=2),
        "m4-report.json",
        "application/json",
    )
