# PP1 M4 integration plan (W3-08)

This is the M4 section of the team integration plan used for PR #36,
retained here so the integration log has a repository-accessible reference.
It records the plan before implementation; completion and validation are in
[the integration log](m4-pp1-integration-log.md).

The common plan requires one offline flow through
`argus.orchestration.pipeline.run_once(batch)`, one Streamlit app at
`src/argus/demo/app.py`, fixed shared contracts, clearly labelled simulations,
and an executor stub that runs no cluster commands. Pages use the saved
`st.session_state["record"]` or the same scenario input; reporting logic
returns plain data from the owning module. Tests use fakes, never real LLM calls.

## M4 — Nethmi (Adaptive Tool Orchestration & Token Manager)

**Input → process → output:**

- Input: `TelemetryBatch`.
- Process: compress → pass to M1 → route M2's model call → handle actions (writes through M3) → execute (stub) → hand BLOCKs back to M2 once.
- Output: `PipelineResult` (context, diagnosis, verdicts, executions, feedback diagnosis).

**Status:**

- Merged: compression (F1), the W3-03 gate handling, the offline router, model dispatch with scripted fakes, `run_function2` and fallback.
- Your dashboard is on `feat/local-demo-dashboard` (no PR).

**Left to do:**

1. Review the one-line `pipeline.py` merge fix proposed on PR #25: `run_once` passes the demo's `diagnoser` to your `process_diagnosis(..., feedback_handler=diagnoser)`. Reply there.
2. Keep `pipeline.run_once(batch)` as the single entry from telemetry to result for the demo. If routing should be visible in the flow, propose to Saniru how `run_function2` plugs into `run_once` (M2's call routed, with a labelled fake or the shared LLM client as the adapter).
3. Optional for the demo: a real-provider adapter for `model_dispatch` that uses the shared `argus.llm.client` (after #23 merges). Keep the scripted adapter for tests.
4. The executor stays a labelled stub for PP1 (no cluster). Nothing must ever execute.
5. Dashboard: move your compression, routing and fallback/safety views into `src/argus/demo/pages/4_M4_orchestration.py` (one app, no second `streamlit run` entry). `pyproject.toml` already gets `demo = ["streamlit==1.65.0"]` from #25, so don't add it again. Show compression sizes for the same scenario input, the routing plan and the fallback attempts.
6. Optional: expose plain data for the dashboard from `run_once`, such as original vs compressed size, without changing the shared contracts.
