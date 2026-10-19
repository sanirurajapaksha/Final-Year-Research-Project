"""Dashboard page for M2, Diagnosis (owner: Kaveen).

Shows M2's REAL diagnose() loop on scenario_01: the hypotheses, the belief after every read, the
reads and their results, and the actions M2 proposes. The reads are FAKE: there is no cluster for
PP1, so every kubectl read is answered from canned scenario_01 output
(data/fixtures/m2/scenario_01/reads.json). Nothing is executed. Scoring is rule-based (no LLM).

The page only displays: the data comes from argus.diagnosis.demo.demo_report().
"""

import streamlit as st

from argus.context.service import build_context
from argus.contracts import TelemetryBatch
from argus.demo.run import TELEMETRY
from argus.demo.views import the_run
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
