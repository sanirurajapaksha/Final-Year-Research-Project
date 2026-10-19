# W3-05 fake adapter and fallback runtime

Status: implemented locally for review, 2026-10-18. This is the next prototype
slice after the offline router in PR #24. That PR was open when this work began;
`feat/m4-w3-05-model-fallback` is intentionally based on its router branch.
W3-05 is not complete and no real provider integration is claimed.

## Entry points

- `model_dispatch.dispatch()` routes a batch, invokes a supplied adapter,
  validates its outputs and follows explicit fallback rules.
- `fake_models.ScriptedAdapter` returns queued fake responses or errors for
  each task/model pair. Durations are simulated, with no network or sleeping.
- `budget.EstimatedBudget` retains an estimated-cost balance across sequential
  batches. Use one ledger per incident with a consistent cost unit.
- `python -m argus.orchestration.fake_model_demo --budget 17` demonstrates a
  timeout and an invalid output, each followed by a successful fallback.

Shared contracts and M1, M2 and M3 are unchanged. The original pipeline now
reuses an extracted action/feedback handler with the Function 2 entry point;
its signature and gate behavior remain the same. Callers supply prompts and
task-specific output validators through this local interface. Model outputs
remain data; the dispatcher does not execute proposed actions.

## Explicit policy

`DispatchPolicy` requires the maximum number of attempts per task, a per-call
timeout, retry conditions and an ordered fallback list per task. The initial
call counts as an attempt. Repeating a model ID in the list explicitly requests
a retry on that model. No fallback is selected unless configured.

Retry conditions are `timeout`, `error` and `invalid_output`. Validators return
a validated value or raise an exception. The runtime records an outcome and
estimated charge for every started attempt. Once a call validates successfully,
its task stops; otherwise only configured failure kinds allow another attempt.

Every fallback must reference an existing candidate, meet minimum quality and
remain in the task's TAF layer. Thus a high-scoring low-cost candidate cannot
replace frontier diagnostic reasoning. Unknown or ineligible fallbacks are
configuration errors detected before calls or budget reservations.

These timeout, retry and accounting semantics are prototype choices, not
decisions specified by the TAF. Real provider policy still needs team agreement.

## Estimated accounting and reservations

The request's remaining budget and cost unit must match the ledger's available
balance. The dispatcher first reserves all initially planned calls. It then
processes tasks in the router's deterministic task-ID order.

The full candidate estimate is charged when an attempt starts, even if it
times out, fails or returns invalid output. A fallback must fit the unreserved
balance without consuming another task's initial reservation. If the next
configured fallback is unaffordable, that task stops with `budget_exhausted`;
the dispatcher does not silently skip to another model or relax quality.
Other tasks can still use their initial reservations.

The ledger rejects negative/noninteger amounts and prevents reservation reuse
or cross-ledger spending. Unstarted reservations owned by the batch are released
on exit, including an interrupt. Started-attempt charges are not refunded, and
unrelated existing reservations remain intact.

This is in-memory, sequential accounting of estimates. It neither measures
actual usage nor enforces a real provider spending cap. There is no concurrent
ledger, persisted incident state or settlement against billed usage yet.

## Deadlines and fake behavior

Adapters receive `timeout_ms` and must implement their own transport deadline.
The scripted adapter raises `TimeoutError` when simulated duration exceeds that
limit. The dispatcher also rejects a reply reporting late completion. There is
no background thread or claimed ability to terminate a hung real SDK call.
Real cancellation, late-completion handling and usage reconciliation remain
provider-adapter work.

Scripts are copied on construction and consumed in order. Missing scripted
responses produce a recorded error rather than making a provider call.

## Run the demo

From the checkout with existing dependencies installed:

```powershell
python -m argus.orchestration.fake_model_demo --budget 17
python -m argus.orchestration.fake_model_demo --budget 15
```

With 17 synthetic credits, all four attempts fit: diagnosis timeout (4),
diagnosis fallback (7), invalid parsing response (2), valid parsing fallback
(4). Both tasks succeed, 17 credits are charged and no reservations remain.

With 15 credits, diagnosis recovers but parsing's fallback cannot fit: 13
credits are charged and 2 remain. The second command intentionally exits 1.
An infeasible initial plan starts no calls and consumes no budget. Invalid
configuration exits 2 in the demo.

These are synthetic costs and durations, not API prices, measured model latency
or diagnosis accuracy. No saved historical experiment output was changed.

## Validation

Final follow-up: 437 tests passed with one Unix-only memory-cap skip and no
deselections under the current runtime, with the optional SciPy tests included.
The previously excluded sandbox timeout test now passes without M3 changes.
The narrower counts below are retained as earlier validation history.

A subsequent audit covered all 17 modified/new files and passed 436 tests,
including the optional M3 evaluation tests after isolated installation of the
already-declared SciPy dependency. One platform skip and one known Windows
timeout-test deselection remain. It also checked all four demo exit paths and
fixed feedback validation for mutated shared models. See the latest evidence in
[the Function 2 entry-point documentation](m4-w3-05-function2-entry.md).
The counts below describe the earlier, narrower run.

Local validation on 2026-10-18: 156 focused orchestration/gate checks passed.
The broader available suite passed 407 tests with one platform skip and one
deselection of the previously documented Windows timeout test
`test_timeout_returns_no_result`. The optional M3 evaluation module
`tests/unit/safety/test_evaluate.py` was excluded because SciPy is unavailable in
the local environment. This is not a full-suite or CI pass claim. Ruff lint,
formatting and `git diff --check` passed. The demo was also run through its module
entry point with budget 17, producing four attempts and a final estimated
balance of zero.

Checks used bundled Python with checkout `src` and existing
`.venv/Lib/site-packages` on `PYTHONPATH`, a writable pytest `--basetemp` and
`-p no:cacheprovider`, matching the existing local interpreter workaround.

Unit coverage checks reservation conservation, single-use tokens, failure
charging, protected initial allocations, multi-batch balances, retry limits,
same-model retries, explicit stop conditions, output validation, cancellation
cleanup, empty batches and invalid policy. Script tests cover copying, call
order, exhausted scripts and simulated deadlines.

`tests/integration/test_m4_model_fallback_gate.py` validates a fake fallback
response as the existing `DiagnosisResult`. Dispatch alone calls neither the
gate nor executor. Explicit action handoff then uses the real M3 gate and a
recording execution stub to verify APPROVE/BLOCK, counterexamples and exact
command preservation. No cluster command runs.

