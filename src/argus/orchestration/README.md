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
- `router.route(RoutingRequest) -> RoutingPlan`: W3-05 offline prototype.
  Solves a binary linear assignment with the existing Z3 dependency. Budget,
  integer cost units, quality-estimate provenance and objective (`max_quality`
  or `min_cost`) are required inputs. Basic parsing uses low-cost candidates;
  diagnostic reasoning uses frontier candidates. Returns a complete optimal
  assignment or an empty infeasible/solver-error result. It makes no model calls.
- `model_dispatch.dispatch()`: next W3-05 prototype slice. Invokes a supplied
  adapter with explicit output validators and fallback policy. The included
  `fake_models.ScriptedAdapter` simulates calls and deadlines without a provider.
  `budget.EstimatedBudget` reserves initial allocations and charges the full
  estimate for every started attempt across sequential incident batches.
- `function2.run_function2(SemanticContext, ...) -> Function2Result`: shared-model
  entry point for one routed diagnostic task. Validates `DiagnosisResult` and
  reuses W3-03 handling for `ProposedAction`, `SafetyVerdict`, `ExecutionResult`
  and BLOCK feedback. Failure to obtain a valid diagnosis performs no actions.
  See [the entry-point contract](../../../docs/functions/m4-w3-05-function2-entry.md).
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
Live fact collection, real provider calls and cluster execution remain separate work.

Run the fake fallback example:

```powershell
python -m argus.orchestration.fake_model_demo --budget 17
```

Budget 17 funds both fallbacks; budget 15 demonstrates a budget stop.
See [the runtime policy](../../../docs/functions/m4-w3-05-fallback-runtime.md)
for the simulated deadline and estimated-accounting limits. Neither the model
dispatcher nor the demo executes commands produced by a model.

Run an offline routing measurement from the checkout with the existing project
dependencies, using a fresh output directory:

```powershell
python -m argus.orchestration.router_benchmark data/fixtures/m4/routing_synthetic.json --budgets 5 9 11 --repetitions 20 --output-dir scratch/m4-routing-measurement
```

The runner saves exact input, source snapshots/hashes, environment and Git
provenance, plans, raw timing CSV and per-budget summaries. It refuses existing
output directories. The first call in the process and per-case warmups are
separate from repeated measurements. Timing excludes imports and provider calls.
The sample's scores and costs are synthetic; this is not API cost or diagnosis
accuracy evidence. See [the routing policy](../../../docs/functions/m4-w3-05-routing-policy.md).

**Planned work** (from the proposal and the PP1 plan; yours to confirm or replace):
- Function 1: further compression must preserve every record, duplicate, field and original record order. Do not drop, merge, deduplicate or select rows. Noise pruning belongs to M1.
- Function 2: connect the tested fake-adapter runtime to agreed real model
  adapters, enforce transport deadlines and reconcile actual incident usage.
  Retry/fallback settings and estimated charging remain explicit prototype
  policy. W3-03 handles gate integration; the executor remains a labelled stub.
- PP1 measurements: `original_size` and `compressed_size` are UTF-8 byte counts. Token counting and savings remain pending model/tokenizer selection and agreed measurement rules. Orchestration latency and API cost evaluation remain planned.
- W2-08 contract v1 compression work is completed and merged. Token evaluation
  remains separate; see [F1](../../../docs/functions/m4-F1-telemetry-compression.md)
  and the [token-counting proposal](../../../docs/functions/m4-token-counting-proposal.md).

**Rules that affect other modules:**
- Commands bypass compression: M3 must receive `ProposedAction.command` byte-exact.
- No write executes without an APPROVE verdict from M3. `tests/integration/test_pipeline.py` checks this.

**Internal layout:** up to you. Put tests in `tests/unit/orchestration/`.
