# M4: Adaptive Tool Orchestration & Token Manager

**Owner:** Nethmi Herath

**Role in the flow:** M4 is the orchestrator. Telemetry enters through M4, which preprocesses and compresses it for M1. M4 routes model calls and passes M1's context to M2. Write commands go M2 → M4 → M3. M4's execution handler runs approved commands.

**Entry points:**
- `service.compress(TelemetryBatch) -> CompressedTelemetry`: implemented JSON-encoded TSV with one shared header. Copies contract v1 `alert_time`, including its optional `None` default.
- `service.execute(ProposedAction) -> ExecutionResult`. Call it only for reads, or for writes M3 approved. The stub never runs anything.
- `execution.handle_action(ProposedAction) -> ActionResult`: W3-03 handler.
  Writes call M3 in-process and reach the executor only with an `APPROVE`
  verdict for the exact command. Gate errors, missing verdicts and mismatched
  commands produce a fail-closed `BLOCK`. Reads bypass the gate.
- `pipeline.run_once(TelemetryBatch)`: the end-to-end wiring, framework-agnostic until the team picks CrewAI or LangGraph.

W3-03 hands all blocked verdicts, including their reasons and available
counterexamples, back to `diagnose(context, feedback=...)` once after the initial
action batch. Its response is retained in `PipelineResult.feedback_diagnosis`;
revised actions are not automatically executed. M2 remains a stub that does not
interpret feedback yet.

The handler and pipeline accept optional gate/executor callables for recorded
integration runs. `tests/integration/test_m4_gate_handoff.py` uses the real M3
gate with the existing hotel-reservation snapshot and a recording executor stub.
By default M3 blocks writes without a snapshot and the executor runs no commands.
Live fact collection, model routing and cluster execution remain separate work.

**Planned work** (from the proposal and the PP1 plan; yours to confirm or replace):
- Function 1: further compression must preserve every record, duplicate, field and original record order. Do not drop, merge, deduplicate or select rows. Noise pruning belongs to M1.
- Function 2: ILP model router and the execution handler, which routes writes to M3 and executes approved ones on the dev cluster.
- PP1 measurements: `original_size` and `compressed_size` are UTF-8 byte counts. Token counting and savings remain pending model/tokenizer selection and agreed measurement rules. Orchestration latency and API cost evaluation remain planned.
- Contract v1 integration is implemented; W2-08 is not complete. See [F1](../../../docs/functions/m4-F1-telemetry-compression.md) and the [token-counting proposal](../../../docs/functions/m4-token-counting-proposal.md).

**Rules that affect other modules:**
- Commands bypass compression: M3 must receive `ProposedAction.command` byte-exact.
- No write executes without an APPROVE verdict from M3. `tests/integration/test_pipeline.py` checks this.

**Internal layout:** up to you. Put tests in `tests/unit/orchestration/`.
