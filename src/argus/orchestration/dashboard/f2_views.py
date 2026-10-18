"""Streamlit views for the existing M4 offline routing and dispatch runtime."""

import json

import streamlit as st

from argus.orchestration.dashboard.scenarios import FAILURES, routing_demo, safety_demo


def download(label, result, filename):
    st.download_button(label, json.dumps(result, ensure_ascii=False, indent=2), filename, "application/json")


def show_routing():
    st.header("Routing & Budget")
    st.caption(
        "Two synthetic tasks share one budget. Parsing uses low-cost models; diagnosis uses frontier models."
    )
    budget = st.slider("Shared budget (synthetic credits)", 0, 20, 9)
    quality = st.slider("Minimum quality for each task (synthetic score)", 0, 100, 70)
    objective = st.selectbox("Optimization objective", ["max_quality", "min_cost"])
    try:
        output = routing_demo(budget, quality, objective)
    except (OSError, ValueError) as error:
        st.error(f"Cannot load routing scenario: {error}")
        return
    plan = output["plan"]
    st.dataframe(output["candidates"], hide_index=True, width="stretch")
    st.caption("Wrong-layer candidates stay ineligible even when their synthetic quality is higher.")
    if plan["status"] == "optimal":
        cards = st.columns(3)
        cards[0].metric("Planned credits", plan["total_estimated_cost_units"])
        cards[1].metric("Unallocated credits", budget - plan["total_estimated_cost_units"])
        cards[2].metric("Total estimated quality", plan["total_estimated_quality"])
        st.success("Optimal assignment found")
        st.dataframe(plan["assignments"], hide_index=True, width="stretch")
    else:
        st.warning(f"{plan['status']}: {plan['reason']}")
        st.info("No complete plan was selected. No model calls were started.")
    st.caption(
        "Planning only. Credits and quality are invented estimates, not API prices or measured accuracy."
    )
    download("Download routing results", output, "routing-results.json")


def show_safety():
    st.header("Fallback & Safety")
    st.caption(
        "Independent scripted diagnosis → output validation → M3 gate → no-op executor → BLOCK feedback"
    )
    budget = st.slider("Attempt budget (synthetic credits)", 0, 10, 5)
    failure = st.selectbox("Primary model outcome", FAILURES, index=1)
    replicas = st.selectbox("Proposed geo replicas", [1, 2], index=0)
    st.info(
        "Primary costs 2 credits; fallback costs 3. Every started attempt is charged, including failures."
    )
    st.caption(
        "At 5 credits fallback can succeed; at 4 it stops; below 2 the initial plan is infeasible. "
        "The snapshot requires at least 2 geo replicas. Gate errors also BLOCK."
    )
    selection = (budget, failure, replicas)
    if st.button("Run scripted scenario", type="primary"):
        try:
            with st.spinner("Running local model script and snapshot safety check…"):
                result = safety_demo(*selection)
            st.session_state["safety_demo_result"] = (selection, result)
        except (OSError, ValueError) as error:
            st.session_state.pop("safety_demo_result", None)
            st.error(f"Cannot run safety scenario: {error}")
    saved = st.session_state.get("safety_demo_result")
    if saved is None or saved[0] != selection:
        st.info("Run the scenario to see results for these settings.")
        return
    output = saved[1]
    balance = output["budget"]
    cards = st.columns(3)
    for card, label, field in zip(
        cards,
        ["Spent credits", "Reserved credits", "Available credits"],
        ["spent_units", "reserved_units", "available_units"],
        strict=True,
    ):
        card.metric(label, balance[field])
    if output["plan"]["status"] != "optimal":
        st.warning(f"{output['plan']['status']}: {output['plan']['reason']}")
    st.subheader("Attempt timeline")
    for index, attempt in enumerate(output["attempts"], 1):
        st.write(
            f"{index}. {attempt['model_id']} → {attempt['status']} "
            f"· {attempt['charged_estimated_units']} credits charged"
        )
        if attempt["reason"]:
            st.caption(attempt["reason"])
    if output["tasks"]:
        st.dataframe(output["tasks"], hide_index=True, width="stretch")
    if output["diagnosis"] is None:
        st.warning("No valid DiagnosisResult: safety gate, executor and feedback were not invoked.")
    else:
        st.success("Model output validated as DiagnosisResult")
        with st.expander("Scripted diagnosis and proposed actions"):
            st.json(output["diagnosis"])
        st.subheader("M3 verdicts")
        for verdict in output["verdicts"]:
            st.code(verdict["command"], language="text")
            st.write(f"{verdict['decision']}: {verdict['reason']}")
            if verdict.get("counterexample"):
                st.json(verdict["counterexample"])
        st.subheader("Executor handoff")
        st.caption("Reads bypass M3; only approved writes reach this stub. All executed flags remain false.")
        st.dataframe(output["executions"], hide_index=True, width="stretch")
        st.subheader("BLOCK feedback to M2 callback")
        if output["feedback_received"]:
            st.json(output["feedback_received"])
            st.write("Scripted revised proposal retained; revised actions are not executed.")
            st.json(output["feedback_diagnosis"])
        else:
            st.info("No blocked verdict was sent to the feedback callback.")
        if output["feedback_error"]:
            st.error(output["feedback_error"])
    with st.expander("Scenario inputs, policy and hand-written snapshot"):
        st.json({key: output[key] for key in ("context", "snapshot", "request", "policy")})
    st.caption(
        "Simulated model failures and deadlines; local estimated accounting. "
        "No provider calls or cluster commands."
    )
    download("Download scenario results", output, "fallback-safety-results.json")
