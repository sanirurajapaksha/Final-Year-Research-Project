"""Dashboard page for M2, Diagnosis (owner: Kaveen).

Shows M2's REAL diagnose() loop on scenario_01: the hypotheses, the belief after every read, the
reads and their results, and the actions M2 proposes. The reads are FAKE: there is no cluster for
PP1, so every kubectl read is answered from canned scenario_01 output
(data/fixtures/m2/scenario_01/reads.json). Nothing is executed. Scoring is rule-based (no LLM).

It also shows M2's answer when M3 blocks its fix: the BLOCK from page 1's run if there is one,
otherwise a hand-made BLOCK labelled SIMULATED. A toggle re-runs M2 with no reads at all.

The page only displays: the data comes from argus.diagnosis.demo (demo_report() and its helpers).
"""

import pandas as pd
import streamlit as st

from argus.context.service import build_context
from argus.contracts import SafetyVerdict, SemanticContext, TelemetryBatch
from argus.demo.run import TELEMETRY
from argus.demo.views import the_run
from argus.diagnosis.core.belief import H0
from argus.diagnosis.demo import (
    demo_report,
    no_cluster_report,
    prior_beliefs,
    read_verdicts,
    run_blocks,
    simulated_block,
)
from argus.orchestration.service import compress


def scenario_context(telemetry_path: str) -> SemanticContext:
    """The same scenario input as page 1: M4 compresses the telemetry -> M1 builds the context."""
    with open(telemetry_path, encoding="utf-8") as file:
        batch = TelemetryBatch.model_validate_json(file.read())
    return build_context(compress(batch))


@st.cache_data
def m2_report(telemetry_path: str, no_cluster: bool) -> dict:
    """M2's first answer on that context. Cached, so switching pages doesn't recompute it."""
    return feedback_report(telemetry_path, [], no_cluster)


def feedback_report(telemetry_path: str, feedback: list[SafetyVerdict], no_cluster: bool) -> dict:
    """M2's answer given M3's BLOCK verdicts (none on the first call). With no_cluster, no reads at all."""
    context = scenario_context(telemetry_path)
    if no_cluster:
        return no_cluster_report(context, feedback)
    return demo_report(context, feedback)


st.title("M2: diagnosis")
st.caption(
    "M2 turns M1's context into competing root-cause hypotheses, runs one read per hypothesis, "
    "updates its belief after each result, and proposes a read and a fix for the best one."
)

record = the_run()
no_cluster = st.toggle(
    "No cluster at all: run M2 with no reads, not even the canned ones",
    help="Shows what M2 does when every read fails: it should stop and say it is unsure.",
)
report = m2_report(str(TELEMETRY), no_cluster)

st.warning(
    f"{report['reads_source']}. There is no cluster in PP1 and nothing is executed. "
    "Scoring is rule-based (no LLM)."
)

st.subheader("Input from M1")
st.markdown(f"Namespace: `{report['namespace']}`. Candidate services and their prior weight:")
st.dataframe(report["candidates"], hide_index=True)
st.caption(
    "Weight 1.5 = deepest failing service, 1.0 = on the failing path, 0.5 = any other known service. "
    "M2 makes hypotheses about these services, the heaviest first."
)

st.subheader("Summary")
hypotheses = report["hypotheses"]
left, middle, right, last = st.columns(4)
if hypotheses:
    top = hypotheses[0]
    left.metric("Top hypothesis", f"{top['component']} [{top['layer']}]")
    middle.metric("Its probability", f"{top['probability']:.0%}")
else:
    left.metric("Top hypothesis", "none")
    middle.metric("Its probability", "-")
right.metric("Stop reason", report["stop_reason"])
last.metric("Reads run", len(report["reads"]))
if report["low_confidence"]:
    st.warning("Low confidence: M2 stopped without a clear winner. Treat the top hypothesis as a guess.")

st.subheader("Hypotheses, best first")
priors = prior_beliefs(report)
rows = []
for hypothesis in hypotheses:
    status = hypothesis["status"]
    if status == "pruned":
        status = "✗ pruned"
    prior = priors.get(hypothesis["id"], 0.0)
    rows.append(
        {
            "id": hypothesis["id"],
            "component": hypothesis["component"],
            "layer": hypothesis["layer"],
            "fault": hypothesis["fault"],
            "prior → final": f"{prior:.0%} → {hypothesis['probability']:.0%}",
            "probability": f"{hypothesis['probability']:.1%}",
            "status": status,
        }
    )
st.dataframe(rows, hide_index=True)
st.caption(
    "prior → final: the belief before any read, and after the last one. "
    "✗ pruned: its belief fell below the pruning threshold (eps), so M2 stopped testing it."
)

st.subheader("Belief after each step")
chart_rows = []
step_rows = []
for one_round in report["belief_rounds"]:
    chart_rows.append(one_round["belief"])
    verdicts = []
    for hypothesis_id, verdict in one_round["verdicts"].items():
        verdicts.append(f"{hypothesis_id}: {verdict}")
    step_rows.append(
        {
            "step": one_round["step"],
            "event": one_round["event"],
            "read": one_round["evidence"] or "-",
            "verdicts": ", ".join(verdicts) or "-",
        }
    )
steps = [one_round["step"] for one_round in report["belief_rounds"]]
belief = pd.DataFrame(chart_rows, index=pd.Index(steps, name="step"))
belief = belief.rename(columns={H0: "H0 (none of these)"})
st.line_chart(belief)
st.dataframe(step_rows, hide_index=True)

st.subheader("Reads and results")
st.caption(report["reads_source"])
hypotheses_by_id = {}
for hypothesis in hypotheses:
    hypotheses_by_id[hypothesis["id"]] = hypothesis
verdicts_by_read = read_verdicts(report)
for read in report["reads"]:
    status = "ok" if read["ok"] else "failed"
    with st.expander(f"{read['id']} · {read['hypothesis']} · {status}"):
        tested = hypotheses_by_id.get(read["hypothesis"])
        if tested is not None:
            st.markdown(f"Tests **{tested['component']} [{tested['layer']}]** {tested['fault']}.")
            st.markdown(f"Expected if true: *{tested['expected']}*")
        st.code(read["command"], language="bash")
        st.code(read["output"], language="text")
        verdicts = []
        for hypothesis_id, verdict in verdicts_by_read.get(read["id"], {}).items():
            verdicts.append(f"{hypothesis_id}: {verdict}")
        st.markdown("Verdict: " + (", ".join(verdicts) or "none"))

st.subheader("Proposed actions")
st.caption("Nothing here runs. Every WRITE goes to M3 (the safety gate) via M4 before anything could run.")
for action in report["diagnosis"]["actions"]:
    kind = "WRITE" if action["is_write"] else "READ"
    st.markdown(f"**{kind}** · namespace `{action['target_namespace']}`: {action['rationale']}")
    st.code(action["command"], language="bash")

st.subheader("When M3 blocks M2's fix")
fix = None
for action in report["diagnosis"]["actions"]:
    if action["is_write"] and fix is None:
        fix = action["command"]
if fix is None:
    st.caption("M2 proposed no write this time, so there is nothing for M3 to block.")
else:
    feedback = run_blocks(record["rounds"])
    blocked_in_run = False
    for verdict in feedback:
        if verdict.command == fix:
            blocked_in_run = True
    if blocked_in_run:
        st.markdown("In page 1's run M3 blocked this fix, and M4 handed the verdict back to M2.")
    else:
        feedback.append(simulated_block(fix))
        st.warning(
            "SIMULATED BLOCK: page 1's run did not block this exact command, so a hand-made BLOCK "
            "is used here to show what M2 does when M3 says no. It is not a real M3 verdict."
        )
    revised = feedback_report(str(TELEMETRY), feedback, no_cluster)
    st.markdown("M2's revised actions (it never proposes a blocked command again):")
    for action in revised["diagnosis"]["actions"]:
        kind = "WRITE" if action["is_write"] else "READ"
        st.markdown(f"**{kind}**: {action['rationale']}")
        st.code(action["command"], language="bash")
    if revised["diagnosis"]["hypotheses"]:
        top_revised = revised["diagnosis"]["hypotheses"][0]
        for line in top_revised["evidence"]:
            if line.startswith("M3 blocked the fix"):
                st.markdown(f"Why there is no write now: {line}")

st.subheader("M2 in this run's rounds (from page 1)")
st.caption(
    "What page 1's pipeline got from M2. Page 1 may still use the SIMULATED M2 (demo/scenario.py) "
    "until run.py switches to demo_diagnose, so these rows can differ from the real M2 above."
)
for number, one_round in enumerate(record["rounds"], start=1):
    st.markdown(f"**Round {number}: {one_round['title']}**")
    st.table(one_round["hypotheses"])
