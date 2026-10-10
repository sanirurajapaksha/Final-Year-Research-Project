# M4: Adaptive Tool Orchestration & Token Manager

**Owner:** Nethmi Herath

**Role in the flow:** M4 is the orchestrator. Telemetry enters through M4, which preprocesses and compresses it for M1. M4 routes model calls and passes M1's context to M2. Write commands go M2 → M4 → M3. M4's execution handler runs approved commands.

**Entry points** (stubs for now):
- `service.compress(TelemetryBatch) -> CompressedTelemetry`
- `service.execute(ProposedAction) -> ExecutionResult`. Call it only for reads, or for writes M3 approved. The stub never runs anything.
- `pipeline.run_once(TelemetryBatch)`: the end-to-end wiring, framework-agnostic until the team picks CrewAI or LangGraph.

**Planned work** (from the proposal and the PP1 plan; yours to confirm or replace):
- Function 1: telemetry preprocessing and knapsack payload compression. It must be lossless for the fields M1 and M3 need.
- Function 2: ILP model router and the execution handler, which routes writes to M3 and executes approved ones on the dev cluster.
- Metrics: token-compression ratio, orchestration latency, API cost savings.

**Rules that affect other modules:**
- Commands bypass compression: M3 must receive `ProposedAction.command` byte-exact.
- No write executes without an APPROVE verdict from M3. `tests/integration/test_pipeline.py` checks this.

**Internal layout:** up to you. Put tests in `tests/unit/orchestration/`.
