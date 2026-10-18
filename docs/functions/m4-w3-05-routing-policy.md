# W3-05 routing policy proposal

Status: offline prototype implemented for review, 2026-10-17. Implementation
choices below are not claimed as team-approved policy. W3-03 is merged; W3-05
remains in progress pending provider, accounting and fallback integration.

## First implementation slice

Build an offline router that chooses one model per task across a batch sharing
one remaining incident budget. Use synthetic candidate identities and explicitly
supplied cost and quality estimates. Do not make provider calls or configure a
real spending limit in this slice.

## Requirements established by the TAF

Source: `C:/Users/nethm/Downloads/Research/TAF-J26-SE-305.pdf`, section 7 on
page 3 and Herath P.A.G.N.T's row in section 9 on page 6. The M4 row was also
checked visually against the rendered page.

- Adapt QC-Opt for SRE using mathematical, budget-aware LP routing.
- Direct basic telemetry parsing to the low-cost open-source layer.
- Direct complex diagnostic reasoning, including competing root-cause
  hypotheses for compound failures, to the frontier layer.
- Preserve the frontier layer's role in deep reasoning while reducing cost.

The TAF mentions Groq and OpenRouter as examples of access to open-source
models. It does not select either provider. GPT-4o and Claude 3.5 appear in its
description of existing systems, not as approved development model choices.

The TAF does not set a numeric budget, prices, a quality scale, a mathematical
objective, an LP/ILP solver package, or fallback/retry accounting. Its Z3
requirement belongs to M3 safety verification; it is not a selection of M4's
routing solver. Its large token-consumption figure describes the motivating
problem, not an incident spending cap. These distinctions must survive into code
and evaluation notes.

The older personal M4 implementation plan proposes maximizing total quality
subject to budget and minimum-quality constraints. The current F2 specification
leaves the objective and solver pending. The policy below is a concrete proposal
to reconcile those documents, not evidence of a team decision.

## Proposed local interface

Keep these types within `argus.orchestration`, separate from shared contracts
until the affected owners agree on a cross-module interface.

| Input | Proposed fields and meaning |
|---|---|
| Routing task | Unique `task_id`, `task_kind` (`telemetry_parsing` or `diagnostic_reasoning` initially), integer `min_quality` on a proposed 0–100 scale |
| Candidate estimate | `task_id`, `model_id`, `layer` (`low_cost` or `frontier`), nonnegative integer `estimated_cost_units`, integer `quality` on the same scale |
| Routing request | Tasks, candidate estimates, nonnegative integer `remaining_budget_units` |
| Estimate provenance | Explicit cost-unit definition and quality-estimate source; synthetic examples are labelled as such |

Every cost within a request must use the same unit. Integer units avoid implicit
currency rounding; the eventual provider adapter must define its conversion and
rounding rules. No default dollar budget or actual model price is implied.

Implemented local entry point: `router.route(request) -> RoutingPlan`. The
immutable Pydantic request requires cost and quality provenance and an explicit
objective; it rejects unknown fields and inconsistent model-layer declarations.

The plan returns a status (`optimal`, `infeasible`, or `solver_error`), selected
task/model pairs, total estimated cost, total estimated quality and a reason for
failure. Failed plans contain no partial assignment. Invalid requests raise a
validation error before solving. An empty task batch returns an empty successful
plan at zero cost.

Reject duplicate task IDs, duplicate task/model candidate pairs, unknown task
references, noninteger costs, negative values and quality outside 0–100. A valid
task with no eligible candidate produces an infeasible plan.

## Proposed optimization

For each candidate pair, use a binary variable `x[task, model]`:

- Choose exactly one candidate for every task.
- Enforce task/layer eligibility: basic parsing uses the low-cost layer;
  complex diagnostic reasoning uses the frontier layer. A quality score must
  not override this TAF requirement. Additional task kinds or fallback promotion
  need an explicit policy before they become eligible.
- Every selected candidate meets that task's minimum quality.
- Sum of selected estimated costs is at most the remaining shared budget.
- Require an explicit objective: `max_quality` maximizes total estimated quality
  then minimizes cost; `min_cost` minimizes cost then maximizes quality. These
  are configurable prototype policies, not objectives specified by the TAF.
- Break remaining ties deterministically by model ID in task-ID order.

Use a proven optimal solver result before returning an optimal plan. Infeasible,
unknown or failed solves must not trigger model calls. Exhaustive enumeration is
an independent test oracle for small examples, not the production solver.

The prototype uses the already pinned Z3 dependency with binary variables,
linear cost/quality constraints and lexicographic objectives. It checks solver
status and objective bounds before returning an optimal plan. The checking
timeout is configurable; it does not bound Python validation/encoding time.
This implementation choice does not establish team approval of the routing
solver. The TAF does not explicitly mandate ILP or quality maximization.

## Synthetic example

These values are invented test data, not prices or measured model accuracy.

| Task | Minimum quality | Candidate | Cost units | Quality |
|---|---:|---|---:|---:|
| summarize | 75 | fixture-cheap | 3 | 80 |
| summarize | 75 | fixture-strong | 7 | 94 |
| diagnose | 80 | fixture-cheap | 2 | 68 |
| diagnose | 80 | fixture-strong | 5 | 90 |

For this example, `summarize` means basic telemetry parsing. The cheap candidate
is in the low-cost layer and the strong candidate is in the frontier layer.
At budget 8, select cheap summarization and strong diagnosis: cost 8, quality
170. At budget 12 the same assignment remains eligible: a larger budget does not
remove the task/layer constraint. At budget 7, no eligible assignment fits.
Strong-for-all is a separate experimental baseline, explicitly bypassing the
hybrid router's layer policy. Report its quality, cost and budget violations
separately rather than calling it a feasible hybrid plan.

## Calls, fallback and incident accounting

The first slice returns decisions only. Model invocation, output validation,
timeouts and fallback require a separate adapter and explicit policy. Do not
silently reroute to a provider, relax minimum quality or spend beyond budget.

Before enabling calls, agree on task-specific output schemas, timeout limits,
retry counts, fallback candidates and accounting for failed attempts. Decide
whether to reserve worst-case attempt costs, how actual usage settles a
reservation and who owns the incident ledger across repeated batches. Planning
cost alone is not billed usage or an enforced live spending cap.

All proposed cluster actions continue through W3-03's `handle_action()`. Routing
and fallback must not bypass M3 approval or alter a proposed command.

## Validation and first metric

Test optimal selection against exhaustive enumeration on small batches. Include
shared-budget competition, exact budget boundaries, infeasible quality/budget,
empty input, invalid input, deterministic ties and solver failures. Verify that
diagnostic tasks cannot select low-cost candidates even with artificially high
quality scores, and that parsing stays in its assigned layer as budgets grow.

After implementation, record routing latency on a defined synthetic case set,
with the number of tasks, candidates, repetitions, solver settings, environment
and source commit. Save fresh config and raw results under `experiments/` and
report cold and warmed timings separately. Synthetic planned cost comparisons
must not be presented as actual API savings or SRE diagnosis accuracy.

The implemented `router_benchmark` CLI saves the request, exact relevant source
snapshots and hashes, Git commit/dirty paths, package versions, plans and raw
timings. It rejects existing output directories. Dirty-source runs are labelled
as such and must not be described as clean-commit evidence. The first route call
in a process is measured separately; per-case warmups and repeated timings are
also separate. This is an offline planning metric, not LLM latency.

## Decisions needed before dependent implementation

Confirm the optimization and tie rules, cost units and quality scale, solver,
task boundaries and local input/output design. Share any newer team decisions
that supersede the current F2 specification. Provider integration additionally
needs model identities, approved prices, budget and fallback/accounting policy.

AI assistance: Codex inspected the merged W3-03 implementation, current F2 spec,
older personal implementation plan and TAF (including visual inspection of page
6), then drafted and revised this proposal. No provider calls, dependency changes
or shared-contract changes were made.
