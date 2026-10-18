# W3-05 Function 2 contract entry point

Implementation ready locally on 2026-10-18 for teammate/PR review. This records
the actual readiness date, not the Planner's original 14 October target. It does
not claim team approval of the remaining model/provider policies.

## Public entry point

```python
from argus.orchestration.function2 import run_function2

result = run_function2(
    context,
    request=request,
    adapter=adapter,
    policy=policy,
    budget=budget,
    # Optional: gate=recorded_gate, executor=labelled_stub,
    # feedback_handler=local_m2_feedback_handler,
    # prompt_builder=m2_prompt_builder,
)
```

The caller supplies the routing configuration, adapter, policy and incident
ledger described in [the fallback runtime](m4-w3-05-fallback-runtime.md).
The entry point accepts exactly one `diagnostic_reasoning` task per call.
`model_dispatch.dispatch()` remains available for general multi-task routing.
This entry point does not add telemetry parsing work to M1 or implement M2's RCA.

## Existing shared contracts

| Boundary | Existing model and behavior |
|---|---|
| M1 to M4 | Input is `SemanticContext`. The entry revalidates and copies it; it does not mutate the caller's context. |
| Configured model/M2 adapter to M4 | Output is validated as `DiagnosisResult`, including its `Hypothesis` and `ProposedAction` fields. An already constructed mutable model is also revalidated. |
| M4 to M3 | Every `ProposedAction` marked as a write goes through the existing W3-03 action handler. The command is unchanged. |
| M3 to M4 | Existing `SafetyVerdict` with `GateDecision.APPROVE` or `BLOCK`; raw Z3 SAT/UNSAT is never used as execution authorization. |
| M4 execution results | Existing `ExecutionResult` objects. Reads bypass the gate; approved writes reach the configured executor. |
| BLOCK to M2 | Blocked `SafetyVerdict` objects, including counterexamples, are handed to the existing feedback callback once. The returned `DiagnosisResult` is validated and retained without executing revised actions. |

No files in `src/argus/contracts/` were changed. Routing estimates, policy,
budget ledger and attempt metadata stay in local M4 types.

## Adapter input and output

M2 owns the diagnostic prompt and hypothesis construction. M4 owns routing,
budget and dispatch around that reasoning. Supply `prompt_builder(context)` to
provide M2's prompt; it must return a string and receives an isolated context
copy. Builder errors or invalid return values fail before any budget is spent.
This hook does not implement or replace M2's diagnosis algorithm. Agreement on
the real M2 adapter remains with its owner before integration/merge.

Without a builder, the fake adapter receives a placeholder JSON envelope with
two keys. It contains no diagnostic instructions or schema and must not be
treated as a real-provider prompt:

```json
{
  "output_contract": "DiagnosisResult",
  "context": {"...": "the complete SemanticContext JSON representation"}
}
```

All context fields are retained, including Unicode, dependency edges and signal
timestamps under the shared model's JSON serialization rules. The adapter
returns an `AdapterReply` whose output is a decoded diagnosis object, raw JSON
text or a shared `DiagnosisResult` instance. All three are revalidated with
strict types: string probabilities and string/integer booleans are rejected
rather than coerced. Commands within valid diagnoses are never trimmed or rewritten.

## Result and failures

`Function2Result` is a local M4 dataclass:

- `dispatch`: routing plan, all started attempts, statuses and the estimated
  budget snapshot.
- `pipeline`: `PipelineResult` when a valid diagnosis was produced; otherwise
  `None` and no gate/executor/feedback call occurs.

`PipelineResult` holds the shared context, diagnosis, verdicts, execution results
and optional feedback diagnosis plus `feedback_error` (empty on success).
Feedback is retained as a validated copy, isolated from the handler's object.
Its action-handling implementation is shared
with the original `pipeline.run_once()`, which otherwise retains its existing
behavior and signature.

Wrong context types, invalid context contents and unsupported task shapes fail
before model calls. Initial routing infeasibility, exhausted model attempts and
invalid model output return no pipeline result. Model validation failures can
trigger only the configured fallback policy. Feedback handler or validation
errors populate `pipeline.feedback_error` and leave `feedback_diagnosis=None`.
The caller still receives dispatch attempts, budget spend, gate verdicts and
execution records for actions already handled. No revised actions execute and
feedback errors do not trigger another model call.

## Default stubs and ownership

Without an injected snapshot-aware gate, M3 blocks writes because no cluster
facts are available. The default executor is the existing labelled no-op stub.
The default BLOCK feedback callback is M2's existing stub, which makes no model
call. A supplied feedback callback is a local contract handoff: it must not
silently make provider calls outside the dispatch ledger. Future model feedback
rounds must go through routed, budgeted dispatch.

The fake adapter makes this entry point runnable without API credentials. Real
provider transports, actual usage settlement and production deadline enforcement
remain separate work. M2's diagnostic algorithm and shared schemas are unchanged.

## Evidence

Review fixes validated on 2026-10-18: the full suite passed **453 tests with one
platform skip and no deselections**, including optional SciPy evaluation tests.
The skip is the Unix-only memory-cap test. Ruff lint, formatting and
`git diff --check` passed. Validation used bundled Python with checkout `src`,
existing `.venv/Lib/site-packages` and ignored `scratch/validation-eval-site` on
`PYTHONPATH`, disabled pytest caching and a writable scratch temporary directory.
New regressions cover mixed APPROVE/BLOCK actions followed by invalid feedback
or handler failure, isolated feedback copies, strict JSON/dictionary output,
M2 prompt injection and failures before spend, and non-copyable provider errors.
Codex implemented these review fixes and tests without changing shared models,
dependencies or other owners' modules. M2 owner agreement on the prompt hook is
still required before merge.

Final follow-up on 2026-10-18: the previously excluded sandbox timeout test
passed in a guarded isolated process under the current Python 3.12.14 runtime.
A subsequent complete test selection passed **437 tests with one platform skip
and no deselections**, including the optional SciPy evaluation tests. The only
skip is the Unix-only memory-cap test. No M3 source or test was changed. The
old timeout-test exclusion is no longer required for this local runtime.
Narrow Git attributes also enforce LF for the routing-policy document and the
attributes file, removing the newline warning without changing saved evidence.
The audit below describes the earlier run before these follow-up checks.

Earlier validation audit on 2026-10-18: all 17 modified/new files were checked.
The broader suite passed 436 tests, with one platform skip and one deselected
known Windows timeout test. This run included the optional M3 evaluation tests:
the already-declared SciPy 1.18.1 dependency was installed only into an ignored
scratch directory, alongside NumPy 2.5.4. Project dependencies were unchanged.
Ruff, all-file syntax/whitespace/import checks, local documentation links and
Python/JSON code-block syntax passed. Four actual demo subprocess runs verified
success, budget exhaustion, infeasibility and invalid input. Historical
experiment bytes and their recorded hashes remain intact.

The audit reproduced and fixed one gap: already-constructed, mutated
`DiagnosisResult` objects returned through feedback now have their contents
revalidated before being retained. A regression covers both decoded objects and
mutated shared-model instances. The results below describe the earlier run
before this additional regression and the isolated SciPy installation.

Local validation on 2026-10-18: 176 focused M4 checks passed. The broader
available suite passed 427 tests, with one platform skip and one deselection of
the previously documented Windows timeout test `test_timeout_returns_no_result`.
The optional M3 evaluation module `tests/unit/safety/test_evaluate.py` was
excluded because SciPy is unavailable locally. Ruff lint, formatting and
`git diff --check` passed. No full-suite pass, CI result or teammate approval is
claimed. Tests used the existing bundled-Python/PYTHONPATH workaround and a
writable pytest temporary directory.

`tests/integration/test_m4_function2_contract.py` covers the complete shared
context to diagnosis to real M3 gate path with recorded snapshots and a stub
executor. It checks APPROVE and BLOCK, timeout and invalid-output fallback,
counterexamples delivered to M2, exact commands, context preservation, malformed
shared-model instances, unsupported task shapes, empty diagnoses and the
fail-closed defaults. Existing pipeline and W3-03 tests also run after the shared
action-handler extraction.

AI assistance: Codex inspected the current shared contracts and module entry
points, implemented this M4 facade and reused action handling, then added tests
and documentation. No other owner's module or shared model was modified.
