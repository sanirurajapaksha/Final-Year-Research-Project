"""Argus dashboard: one incident through the whole agent, drawn as a pipeline (like a CI run).

    python -m streamlit run src/argus/demo/app.py      (from the repo root; needs the 'demo' extra)

Choose a sample incident or upload a telemetry file, then press Run. Each stage card fills in as
its module finishes; open a stage under the pipeline to see how that module decided. The run
itself is in flow.py and the modules; this page only draws it.
"""

import json
import time

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from argus.context.report import graph_dot
from argus.contracts import ProposedAction
from argus.demo.flow import SCENARIOS, STAGES, VERIFY, load_telemetry, outcome, routing_record, run_flow
from argus.demo.run import demo_settings
from argus.demo.views import (
    LABELS,
    STYLE,
    card,
    display_data,
    display_text,
    show_steps,
    show_verdict,
    stage_label,
)
from argus.diagnosis.core.belief import H0
from argus.diagnosis.demo import prior_beliefs, read_verdicts
from argus.orchestration.report import OUTCOMES, routing_replay
from argus.safety.gate import check

# Settings and the LLM key from .env in the folder the page is started from (the repo root).
load_dotenv(".env")

PACE_S = 0.8  # pause after each stage when presenting, so the audience can follow; not in the timings
STEP_PACE_S = 0.5  # the same, between the safety layer's own steps

# Example commands for the Formal Verification stage: each shows a different step at work.
FIX_PATCH = (
    "kubectl patch deployment cart -n default -p "
    '\'{"spec":{"template":{"spec":{"containers":[{"name":"cart","env":'
    '[{"name":"CART_ADDR","value":"redis-cart:6379"}]}]}}}}\''
)
EXAMPLES = {
    "Scale cart to 0": "kubectl scale deployment cart --replicas=0 -n default",
    "Scale cart to 2": "kubectl scale deployment cart --replicas=2 -n default",
    "Restart cart (shop)": "kubectl rollout restart deployment/cart -n shop",
    "kube-system pod": "kubectl delete pod coredns-7db6d8ff4d-k2l3m -n kube-system",
    "Shell trick": "kubectl get pods -n default | grep cart",
    "Patch (LLM)": FIX_PATCH,
}


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
            st.error(display_text(f"{stage_label(name)} failed: {type(exc).__name__}: {exc}"))
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
    text = f"**{display_text(result['title'])}**"
    if result["command"]:
        text += f"\n\n`{result['command']}`"
    text += f"\n\n{display_text(result['text'])}"
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
    with st.expander("Compressed input passed to Context Analysis"):
        st.code(details["tsv"], language="text")


def show_context(details: dict) -> None:
    nrr = details["nrr"]
    signals_in, stage1, stage2, compute = st.columns(4)
    if nrr is None:
        signals_in.metric("Signals in", "–")
    else:
        signals_in.metric("Signals in", nrr["raw"])
        stage1.metric("NRR after Stage 1", f"{nrr['stage1']:.2f}")
        stage2.metric("NRR after Stage 2", f"{nrr['stage2']:.2f}", f"{nrr['stage2'] - nrr['stage1']:+.2f}")
    compute.metric("Context analysis time", f"{details['compute_ms']:.2f} ms")
    st.caption(
        "NRR = 1 − kept / signals in (metric, log and k8s records; spans only build the graph). "
        "Labelled NRR and false-prune rate need an answer key; see the Context Analysis experiments."
    )

    graph = details["graph"]
    if graph is None:
        st.info("No traces in the window, so Context Analysis ran its noise filter only (no service graph).")
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
            {
                "": kept,
                "service": signal["service"],
                "signal": signal["name"],
                "evidence": signal["evidence"],
                "why": signal["reason"],
            }
        )
    st.dataframe(rows, hide_index=True)
    st.caption(display_text(details["notes"]))
    st.markdown("**Sent to Root Cause Diagnosis: the SemanticContext**")
    st.json(display_data(details["context"]), expanded=1)


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

    if hypotheses:
        compared = hypotheses[:6]
        ranking = pd.DataFrame(
            [
                {
                    "Hypothesis": f"{hypothesis['id']} · {hypothesis['component']} ({hypothesis['layer']})",
                    "Before reads": 100 * priors.get(hypothesis["id"], 0.0),
                    "After reads": 100 * hypothesis["probability"],
                }
                for hypothesis in compared
            ]
        )
        st.markdown("**How the leading hypotheses changed**")
        st.caption(
            f"Belief in percent, before and after diagnostic reads. "
            f"Showing {len(compared)} of {len(hypotheses)}."
        )
        st.bar_chart(
            ranking,
            x="Hypothesis",
            y=["Before reads", "After reads"],
            horizontal=True,
            stack=False,
            sort=False,
            height=max(220, 48 * len(compared)),
            alt="Starting and final belief for the leading root-cause hypotheses, in percent",
        )

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

    st.markdown("**Diagnosis summary**")
    st.write(display_text(details["report_text"]))
    if hypotheses:
        top = hypotheses[0]
        st.markdown(f"**Leading hypothesis:** {top['component']} · {top['fault']}")
        st.caption(f"Layer: {top['layer']} · Status: {top['status']} · Source: {top['source']}")
        if top["test"]:
            st.write("Test used to check it:")
            st.code(top["test"], language="bash")
        if top["expected"]:
            st.write(f"Expected observation: {top['expected']}")
        verdicts = read_verdicts(details)
        assessments = [
            {
                "read": read["id"],
                "assessment": verdicts[read["id"]][top["id"]],
                "result": "available" if read["ok"] else "unavailable",
            }
            for read in details["reads"]
            if top["id"] in verdicts.get(read["id"], {})
        ]
        if assessments:
            st.caption("How each diagnostic read affected the leading hypothesis:")
            st.dataframe(assessments, hide_index=True)

    st.caption("Reads used to test them (FAKE: canned kubectl output, no cluster):")
    for read in details["reads"]:
        result = "ok" if read["ok"] else "unavailable"
        st.markdown(f"**{read['id']}** tests {read['hypothesis']}: `{read['command']}` ({result})")
        st.code(read["output"][:800], language="text")

    st.caption("What Root Cause Diagnosis proposes:")
    for action in details["diagnosis"]["actions"]:
        kind = "WRITE (goes to the safety layer)" if action["is_write"] else "READ"
        st.markdown(f"**{kind}**: `{action['command']}`")
    if details["diagnosis"]["hypotheses"]:
        for line in details["diagnosis"]["hypotheses"][0]["evidence"]:
            if line.startswith("No write:"):
                st.markdown(display_text(line))


def show_checks(checks: list[dict]) -> None:
    writes = [row for row in checks if row["is_write"]]
    if not writes:
        st.caption("No write was proposed, so there was nothing to verify.")
    for row in writes:
        st.code(row["command"], language="bash")
        if row.get("trace"):
            st.caption("Step by step (open a step to see its data):")
            show_steps(row["trace"], row["verdict"])
            show_verdict(row["verdict"], with_counterexample=False)
        else:
            show_verdict(row["verdict"])


def show_verify(details: dict) -> None:
    st.caption(
        "The safety layer asks Z3 whether ANY end state of the command breaks a rule: unsat → APPROVE; "
        "sat → BLOCK with that end state as the counterexample; an error or unknown → BLOCK."
    )
    show_checks(details["checks"])
    if details["facts"]:
        st.caption("The cluster facts it read (saved kubectl output, read-only):")
        st.dataframe(details["facts"], hide_index=True)
    try_a_command()


def show_feedback(details: dict | None) -> None:
    if details is None:
        st.caption("Nothing was blocked, so Root Cause Diagnosis was not asked again.")
        return
    st.caption("The safety decision and counterexample returned to Root Cause Diagnosis. Its answer:")
    if details["diagnosis"]["hypotheses"]:
        for line in details["diagnosis"]["hypotheses"][0]["evidence"]:
            if line.startswith("M3 blocked"):  # M2 writes this line
                st.markdown(display_text(line))
    for action in details["diagnosis"]["actions"]:
        kind = "WRITE (goes to the safety layer)" if action["is_write"] else "READ"
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
        rows.append({"command": row["command"], "safety layer": decision, "executor": output})
    st.dataframe(rows, hide_index=True)
    st.caption(
        "Reads skip the safety layer; a write reaches the executor only with APPROVE. "
        "The executor is a stub in PP1."
    )


def use_example(command: str) -> None:
    """An example button: put its command in the box and verify it."""
    st.session_state["verify_command"] = command
    st.session_state["verify_now"] = True
    st.session_state["keep_verify_open"] = True


def verify_typed() -> None:
    st.session_state["verify_now"] = True
    st.session_state["keep_verify_open"] = True


def try_a_command() -> None:
    """Inside the Formal Verification stage: verify any other command and draw its steps in order."""
    st.markdown("**Try another command**")
    st.caption(
        "Pick an example or type any kubectl write command. A red step is where checking stopped; "
        "anything that can't be checked is blocked (fail-closed). A patch costs one LLM call (team budget)."
    )
    columns = st.columns(len(EXAMPLES))
    for column, (name, command) in zip(columns, EXAMPLES.items(), strict=True):
        column.button(name, on_click=use_example, args=(command,))
    if "verify_command" not in st.session_state:
        st.session_state["verify_command"] = EXAMPLES["Scale cart to 0"]
    st.text_input("Command", key="verify_command")
    st.button("Verify this command", on_click=verify_typed)

    fresh = st.session_state.pop("verify_now", False)
    if fresh:
        trace = []
        action = ProposedAction(command=st.session_state["verify_command"], is_write=True)
        verdict = check(action, settings=demo_settings(), trace=trace)
        st.session_state["verify_result"] = {"verdict": verdict.model_dump(mode="json"), "trace": trace}
    result = st.session_state.get("verify_result")
    if result is None:
        return
    pace = 0.0
    if fresh and st.session_state.get("present"):
        pace = STEP_PACE_S
    show_steps(result["trace"], result["verdict"], pace)
    show_verdict(result["verdict"], with_counterexample=False)


RENDERERS = {
    "Telemetry": show_telemetry,
    "M4 · Compress": show_compress,
    "M1 · Context": show_context,
    "M2 · Diagnose": show_diagnosis,
    VERIFY: show_verify,
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
    present = st.toggle("Step through slowly (for presenting)", value=True, key="present")
    run = st.button("Run the incident", type="primary", disabled=text is None)


st.title("Argus · incident run")
st.caption(
    "Telemetry goes in, each module runs in turn, and the incident ends with an approved fix "
    "or a hand-over to a human."
)

placeholders = []
for column in st.columns(len(STAGES)):
    placeholders.append(column.empty())

if run:
    st.session_state["keep_verify_open"] = False
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
    # A click inside the Formal Verification panel reruns the page; keep that panel open afterwards.
    keep_open = stage["name"] == VERIFY and st.session_state.get("keep_verify_open", False)
    with st.expander(
        f"{stage_label(stage['name'])} · {LABELS[stage['status']]} · {display_text(stage['headline'])}",
        expanded=keep_open,
    ):
        RENDERERS[stage["name"]](stage["details"])

st.divider()
with st.expander("Action Orchestration: offline model routing replay (not part of the run)"):
    st.caption(
        "The run calls Root Cause Diagnosis directly. This replays its answer through the "
        "orchestration router with scripted model answers and invented costs; no model is called."
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
        "Download orchestration report",
        json.dumps({"compression": compression, "routing_replay": replay}, ensure_ascii=False, indent=2),
        "orchestration-report.json",
        "application/json",
    )
