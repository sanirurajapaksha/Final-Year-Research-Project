"""Dashboard page for M2, Diagnosis (owner: Kaveen).

Shows M2's REAL diagnose() loop on scenario_01: the hypotheses, the belief after every read, the
reads and their results, and the actions M2 proposes. The reads are FAKE: there is no cluster for
PP1, so every kubectl read is answered from canned scenario_01 output
(data/fixtures/m2/scenario_01/reads.json). Nothing is executed. Scoring is rule-based (no LLM).

The page only displays: the data comes from argus.diagnosis.demo.demo_report().
"""

import pandas as pd
import streamlit as st

from argus.context.service import build_context
from argus.contracts import TelemetryBatch
from argus.demo.run import TELEMETRY
from argus.demo.views import the_run
from argus.diagnosis.core.belief import H0
from argus.diagnosis.demo import demo_report
from argus.orchestration.service import compress


@st.cache_data
def m2_report(telemetry_path: str) -> dict:
    """M2 on the same scenario input as page 1: M4 compresses -> M1 builds the context -> M2."""
    with open(telemetry_path, encoding="utf-8") as file:
        batch = TelemetryBatch.model_validate_json(file.read())
    context = build_context(compress(batch))
    return demo_report(context)


st.title("M2: diagnosis")
st.caption(
    "M2 turns M1's context into competing root-cause hypotheses, runs one read per hypothesis, "
    "updates its belief after each result, and proposes a read and a fix for the best one."
)

record = the_run()
report = m2_report(str(TELEMETRY))

st.warning(
    f"{report['reads_source']}. There is no cluster in PP1 and nothing is executed. "
    "Scoring is rule-based (no LLM)."
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
rows = []
for hypothesis in hypotheses:
    status = hypothesis["status"]
    if status == "pruned":
        status = "✗ pruned"
    rows.append(
        {
            "id": hypothesis["id"],
            "component": hypothesis["component"],
            "layer": hypothesis["layer"],
            "fault": hypothesis["fault"],
            "probability": f"{hypothesis['probability']:.1%}",
            "status": status,
        }
    )
st.dataframe(rows, hide_index=True)
st.caption("✗ pruned: its belief fell below the pruning threshold (eps), so M2 stopped testing it.")

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
