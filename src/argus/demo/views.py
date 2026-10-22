"""Display helpers for the dashboard (app.py). Display only: no module logic lives here."""

import html
import re
import time

import streamlit as st

from argus.demo.flow import in_plain_words
from argus.demo.run import verdict_line

LABELS = {
    "waiting": "Waiting",
    "running": "Running…",
    "passed": "Passed",
    "blocked": "Blocked",
    "attention": "Needs a human",
    "skipped": "Skipped",
    "failed": "Failed",
}
MODULE_NAMES = {
    "M1": "Context Analysis",
    "M2": "Root Cause Diagnosis",
    "M3": "Safety Verification",
    "M4": "Action Orchestration",
}
STAGE_LABELS = {
    "Telemetry": "Telemetry",
    "M4 · Compress": "Prepare Telemetry",
    "M1 · Context": "Build Context",
    "M2 · Diagnose": "Diagnose Cause",
    "Formal Verification": "Verify Safety",
    "M2 · Feedback": "Revise Plan",
    "M4 · Execute": "Execute Action",
}
_MODULE_ID = re.compile(r"\bM[1-4]\b")


def display_text(value: str) -> str:
    """Use module names in displayed prose without changing the underlying run data."""
    return _MODULE_ID.sub(lambda match: MODULE_NAMES[match.group()], value)


def display_data(value):
    """Return a UI copy of nested data with readable module names in text fields."""
    if isinstance(value, str):
        return display_text(value)
    if isinstance(value, list):
        return [display_data(item) for item in value]
    if isinstance(value, dict):
        return {key: display_data(item) for key, item in value.items()}
    return value


def stage_label(name: str) -> str:
    """The short label for a pipeline card or detail panel."""
    return STAGE_LABELS.get(name, name)


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

# How one of the safety layer's own steps (from gate.check's trace) is drawn: card colour and label.
STEP_COLOURS = {"passed": "passed", "skipped": "skipped", "stopped": "blocked"}
STEP_LABELS = {"passed": "Passed", "skipped": "Skipped", "stopped": "Stopped here"}


def card(name: str, status: str, line: str, ms: float | None, label: str | None = None) -> str:
    """One card in a pipeline strip (HTML). `status` picks the colour; `label` overrides its text."""
    name = stage_label(name)
    line = display_text(line)
    if len(line) > 90:
        line = line[:87] + "…"
    if label is None:
        label = LABELS[status]
    timing = ""
    if ms is not None:
        timing = f"{ms:.0f} ms"
    return (
        f'<div class="stage {status}"><div class="name">{html.escape(name)}</div>'
        f'<div class="state">{html.escape(label)}</div><div class="line">{html.escape(line)}</div>'
        f'<div class="ms">{timing}</div></div>'
    )


def show_verdict(verdict: dict, with_counterexample: bool = True) -> None:
    """A safety verdict: the decision and reason, the counterexample if any, and the stage timings."""
    text = display_text(f"{verdict_line(verdict)}. {verdict['reason']}")
    if verdict["decision"] == "APPROVE":
        st.success(text)
    else:
        st.error(text)
    if with_counterexample and verdict["counterexample"] is not None:
        st.markdown("Counterexample (an end state that breaks the rule):")
        st.json(verdict["counterexample"])
    stages = []
    for stage, ms in verdict["timings_ms"].items():
        stages.append(f"{stage} {ms:.1f} ms")
    st.caption("Timings: " + ", ".join(stages))


def show_steps(trace: list[dict], verdict: dict, pace_s: float = 0.0) -> None:
    """The safety layer's steps for one command: a card per step, in order, then each step's data in a tab.

    With pace_s, the cards appear one by one (for presenting); the times on them are real.
    """
    columns = st.columns(len(trace))
    for column, step in zip(columns, trace, strict=True):
        column.markdown(step_card(step, verdict), unsafe_allow_html=True)
        if pace_s:
            time.sleep(pace_s)
    tabs = st.tabs([step["step"] for step in trace])
    for tab, step in zip(tabs, trace, strict=True):
        with tab:
            show_step(step)


def step_card(step: dict, verdict: dict) -> str:
    """The card for one step. Z3's card shows its answer; the decision card says why in plain words."""
    colour = STEP_COLOURS[step["status"]]
    label = STEP_LABELS[step["status"]]
    line = step["summary"]
    if step["step"] == "Logic compiler + Z3" and step["status"] == "passed":
        answer = step["data"]["z3_result"]
        label = answer
        if answer == "sat":
            colour, line = "blocked", "found an end state that breaks a rule (a counterexample)"
        elif answer == "unsat":
            colour, line = "passed", "no end state breaks a rule: proved, for the encoded rules"
        else:
            colour, line = "blocked", "undecided, so the command is blocked (fail-closed)"
    if step["step"] == "Decision":
        label = verdict["decision"]
        line = in_plain_words(verdict)
    return card(step["step"], colour, line, step["ms"], label)


def show_step(step: dict) -> None:
    """What one step saw or produced."""
    st.markdown(display_text(step["summary"]))
    data = step["data"]
    if data is None:
        return
    if step["step"] == "Pre-filter":
        st.caption("The command split into words, exactly as kubectl would receive them:")
        st.json(data)
    elif step["step"] in ("Parse", "LLM formulation"):
        st.caption("The action that is checked:")
        st.json(data)
    elif step["step"] == "Cluster facts":
        st.caption("Facts about the target, from read-only kubectl get (saved output in PP1):")
        st.dataframe([data], hide_index=True)
    elif step["step"] == "Logic compiler + Z3":
        st.caption(f"The formula built for Z3 (solved in {data['solver_ms']:.0f} ms):")
        st.code(formula_text(data), language="text")
        if data["counterexample"] is not None:
            st.caption("Z3's model, the counterexample: an end state that breaks a rule.")
            st.json(data["counterexample"])


def formula_text(solved: dict) -> str:
    """Facts(S0) and T(S0, A, S1) and not I(S1), laid out for reading aloud."""
    formula = solved["formula"]
    if formula is None:
        return f"Z3: {solved['z3_result']}"
    lines = ["Is there any state in which ALL of the following hold?", "", "The cluster before the command:"]
    for fact in formula["facts"]:
        lines.append("  " + fact)
    lines.append("")
    lines.append("What the command does:")
    for step in formula["transition"]:
        lines.append("  " + step)
    lines.append("")
    lines.append("At least one rule broken (NOT all of these):")
    for name, rule in formula["invariants"].items():
        lines.append(f"  {name}:  {rule}")
    lines.append("")
    if solved["z3_result"] == "sat":
        lines.append("Z3: sat. Such a state exists, so the command can break a rule: BLOCK.")
    elif solved["z3_result"] == "unsat":
        lines.append("Z3: unsat. No such state exists, so no encoded rule can break: APPROVE.")
    else:
        lines.append(f"Z3: {solved['z3_result']}. Undecided, so the command is blocked (fail-closed).")
    return "\n".join(lines)
