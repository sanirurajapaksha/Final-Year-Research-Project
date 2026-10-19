# Function spec: M4 F2 — Model routing and execution handling

Status: W1-09 design with W3-03 gate/feedback integration merged and a W3-05
offline router implemented for review. Provider routing and live execution remain
planned. See [the prototype routing policy](m4-w3-05-routing-policy.md).

The next local W3-05 slice adds a scripted fake model adapter, explicit retry and
fallback policy, output validators and sequential estimated-budget reservations.
See [the fallback runtime](m4-w3-05-fallback-runtime.md). This does not add real
provider calls, actual billing settlement or a new cluster execution path.

The shared-model entry point is now `function2.run_function2(SemanticContext,
...) -> Function2Result` for one diagnostic task. It validates the configured
adapter's output as `DiagnosisResult` before invoking the same W3-03 action and
feedback handling used by the original pipeline. All shared models are unchanged.
See [the entry-point contract](m4-w3-05-function2-entry.md) for arguments,
failures, default stubs and integration evidence.

| Field | Description |
|---|---|
| Name | F2: Budget-aware model routing and execution handling |
| Owner | Nethmi Herath |
| Input | Existing draft contracts: `SemanticContext` from M1, `DiagnosisResult` and `ProposedAction` from M2, and `SafetyVerdict` from M3. Planned routing inputs: tasks, candidate models, cost estimates, quality estimates, minimum task quality requirements, and the remaining shared incident budget. Their fields and units are pending team decisions. Planned test data uses controlled examples and fake model responses. `data/fixtures/telemetry_sample.json` is an existing pipeline input, not a model routing benchmark. |
| Processing logic | Planned: select models with an integer linear program (ILP), meeting each task's minimum quality requirement within the shared incident budget. Validate model output and apply a fallback policy for model errors, timeouts, and invalid output. Forward M2's command to M3 unchanged. Execute a write only after M3 returns `APPROVE`. On `BLOCK`, execute no command for that action and send its counterexample back to M2. |
| Output | Existing draft models: `ExecutionResult` for execution results and `SafetyVerdict` for safety decisions and feedback. The current `PipelineResult` groups context, diagnosis, verdicts, and execution results; it is a pipeline dataclass, not a shared contract model. Planned model selection and budget reporting outputs have no agreed contract yet. |
| Dependencies | M1 context, M2 diagnosis and feedback handling, M3 safety checks, shared draft contracts, and the M4 pipeline and execution handler. Planned dependencies include model access, cost and quality estimates, shared budget tracking, an ILP solver, and cluster access for execution. No provider, solver package, price, or budget value is agreed here. |
| Test evidence | W3-03 gate/feedback and W3-05 offline optimizer/measurement tests are implemented. Provider/fallback tests and live execution evidence remain planned. No new CI result is claimed. |

## Existing code and contracts

- [M4 F1](m4-F1-telemetry-compression.md) describes the implemented JSON-records-to-TSV conversion.
  Its size fields count UTF-8 bytes, not tokens or model costs.
- `src/argus/orchestration/pipeline.py` currently calls F1, M1, and M2
  in order. W3-03's `execution.handle_action()` sends each write action to M3
  in-process and calls `execute()` only when the decision is
  `GateDecision.APPROVE` and the verdict command exactly matches the proposal.
  Read actions bypass the gate. Gate errors and invalid verdicts block writes.
- `src/argus/orchestration/service.py` still has an execution stub.
  It returns `ExecutionResult` with `executed=False` and runs no command.
  `router.route()` now provides a local offline binary linear optimizer using
  the existing Z3 dependency, explicit budget/estimates/objective, TAF layer
  eligibility, and deterministic ties. It does not call providers or manage
  actual incident spend. Its types remain local to M4; shared contracts are unchanged.
- `ProposedAction.command` must stay exactly as M2 supplied it. It must not
  be trimmed, rewritten, compressed, or passed through F1. M3 must check
  the same command string that would be executed.
- `SafetyVerdict` contains the gate decision, reason, and an optional
  counterexample. The gate decision and the raw solver result are separate.
  Routing must use `GateDecision.APPROVE`, not interpret raw `sat` as approval.
- `diagnose(context, feedback=...)` accepts a list of `SafetyVerdict` objects.
  W3-03 passes blocked verdicts to this entry point once after the action batch
  and retains its response in `PipelineResult.feedback_diagnosis`. It does not
  execute revised actions. The M2 stub does not use that feedback yet.
- The existing shared models are described in
  [../contracts.md](../contracts.md). Telemetry contract v1 is integrated
  into F1. The shared models do not define model
  selection, task quality requirements, or an incident budget contract.

## Confirmed team decisions

- M4 forwards M2's proposed command to M3 unchanged.
- M3 collects its own cluster facts.
- Confirmation source: Saniru Rajapaksha, M3 owner, 2026-10-11.

## Planned implementation

1. Receive the tasks to handle and the available model choices. Use the
   agreed cost and quality estimates for each task and model.
2. Build an ILP, which is a set of rules used to choose between whole options.
   Use a yes-or-no choice for each task and model. Choose one model for each
   task that needs a model, meet that task's minimum quality requirement,
   and keep the total planned cost within the remaining shared incident
   budget. The team must confirm the optimization goal and what happens
   when no choice meets all these rules.
3. Call the selected model and validate its output against the agreed task
   rules. Handle model errors, timeouts, and invalid output through a fallback
   policy. Retry limits, fallback order, and fallback budget handling are
   pending team decisions. A fallback must not bypass the write safety gate.
4. Receive M2's proposed actions. Forward each write action to M3 without
   changing `ProposedAction.command`. Preserve the same string through the
   verdict and any later execution.
5. As confirmed by the M3 owner, M3 collects its own cluster facts. The
   draft design uses read-only queries; the collection details remain pending.
   M4 forwards the action; this spec does not add agreed cluster-fact fields
   to the M4-to-M3 contract. A live-environment adapter file is planned in
   `src/argus/integrations/`; it is not implemented. Live fact collection
   remains planned.
6. Execute a write only after M3 returns `APPROVE` for that action and its
   unchanged command. Missing approval, safety errors, or safety timeouts
   must not allow the write to run.
7. On `BLOCK`, execute nothing for the blocked action. Return the verdict
   and its counterexample to M2 through the feedback path so M2 can revise
   its proposal. If the verdict has no counterexample, pass the reason and
   the existing verdict without inventing one. W3-03 implements this single
   handoff; repeated diagnosis/execution rounds remain to be implemented.
8. Return execution results using `ExecutionResult`. The real execution
   handler and its error and timeout handling remain to be implemented.

## Pending team decisions

- Confirm routing task boundaries, input and output contracts, and which
  modules share the incident budget.
- Confirm budget units, limits, accounting rules, and how estimated costs
  are compared with actual costs. No budget value is set by this spec.
- Confirm model providers and available models, the source of cost data,
  quality measures, and each task's minimum quality requirement.
- Confirm the ILP optimization goal, solver choice, tie handling, and the
  response when no model assignment fits the budget and quality rules.
- Confirm fallback order, retry limits, timeout limits, and invalid-output
  checks. **Fallback budget handling is pending:** decide how failed calls,
  retries, and fallback calls affect the shared incident budget, and what
  happens when the remaining budget cannot cover a fallback.
- Confirm the details of M3's read-only fact collection design. M3 collecting
  its own cluster facts is confirmed.
- Confirm how approval stays valid between the safety check and execution.
- Confirm execution access, command result handling, and the M2 feedback
  loop, including limits on repeated proposals after `BLOCK`.
- Confirm contract v1 with all affected module owners and check the complete
  W1-09 acceptance checklist. This draft does not mark W1-09 complete.

## Test evidence

W3-05 adds offline routing and measurement coverage under
`tests/unit/orchestration/test_router.py` and `test_router_benchmark.py`.
Independent exhaustive enumeration checks optimal assignments. Tests include
both explicit objectives, shared-budget competition, TAF task/layer eligibility,
invalid input, zero costs, solver errors, deterministic ties, raw timing
aggregation and overwrite protection. This is not provider/fallback coverage.
The first synthetic latency run and local validation limits are recorded in
[the experiment notes](../../experiments/2026-10-17_m4_w3_05_offline_router/NOTES.md).

Existing coverage read for this spec:

- `tests/unit/orchestration/test_service.py` checks F1 and that the execution
  stub returns an `ExecutionResult`. It does not prove real execution works.
- `tests/integration/test_pipeline.py` checks that writes receive verdicts
  and do not reach the execution path without approval in the current
  pipeline. It does not test model routing or a completed feedback loop.

W3-03 adds `tests/integration/test_m4_gate_handoff.py`. It exercises the real M3
gate with a recorded snapshot for APPROVE and BLOCK, exact command preservation,
counterexample delivery to M2, rejection without a counterexample, read bypass,
gate errors/timeouts, missing or mismatched approval, and adapter mutation.
Executors are recording stubs; no cluster commands run. M2 receives feedback
through its existing entry point; interpreting it remains M2 work.

Local validation on 2026-10-17: 48 focused tests passed; broader regression
validation passed 251 tests, with 1 platform skip and 1 deselection (the previously
documented Windows `test_timeout_returns_no_result` hang). Ruff lint and format
checks passed. The repository's venv Python launcher points to an unavailable
interpreter, so validation used the bundled Python with `src` and the existing
`.venv/Lib/site-packages` on `PYTHONPATH`, a writable `--basetemp`, and
`-p no:cacheprovider`. These are local results, not CI evidence.

Planned tests, to be added under `tests/unit/orchestration/` and
`tests/integration/` after implementation:

- Happy path: choose models for several tasks within one shared budget,
  meeting every minimum quality requirement. Compare a small ILP result
  with all possible choices to check the agreed optimization goal.
- Failure path: no assignment meets both the budget and quality rules;
  return the team-agreed outcome without making an unplanned model call.
- Check shared budget tracking across tasks and repeated incident rounds.
- Simulate model errors, timeouts, and invalid output. Check fallback order,
  retry limits, and budget handling after the team agrees on the policy.
- Check that a fallback cannot select a model below the agreed task quality
  requirement or bypass M3 approval.
- Check exact command preservation from M2 through M3 to execution,
  including spaces, quotes, tabs, and newlines.
- Use fake cluster queries to check that M3 gathers its own facts through
  read-only queries in the agreed design.
- `APPROVE`: the execution handler receives the approved, unchanged write
  command and returns an `ExecutionResult`.
- `BLOCK`: the blocked command is never executed, and M2 receives the
  verdict and counterexample. Also cover a verdict with no counterexample.
- Missing approval, safety error, or safety timeout: no write executes.
- Simulate execution failure and timeout; check the returned result once
  the execution policy is agreed. These tests must not touch a live cluster.

## Objective -> function -> metric -> evidence

All evaluation items below are planned. No measured results or agreed
numeric targets are claimed.

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Handle incident tasks within a shared budget while meeting minimum quality | ILP model routing | Total incident cost and tasks meeting minimum quality | Planned routing tests and recorded evaluation runs | Pending team decision | Compare agreed routing choices on the same tasks using agreed cost and quality data |
| Recover from model failures under the agreed policy | Fallback handling | Valid task results, fallback cost, and time taken | Planned fake model failure tests | Pending team decision | Inject errors, timeouts, and invalid output; check policy and budget outcomes |
| Execute only approved writes and return blocked proposals to M2 | Safety and execution handling | Writes without approval, exact command matches, and feedback delivered | Planned approval, block, and command preservation tests | Current stub pipeline is a code reference; it is not a live execution baseline | Test with fake gate and execution handlers before any approved cluster evaluation |
