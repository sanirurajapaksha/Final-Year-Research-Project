# W3-05 offline routing prototype

Date: 2026-10-17. Owner: Nethmi Herath. W3-05 remains in progress.

## Scope and provenance

This is an offline measurement of a binary linear routing prototype using the
existing Z3 dependency. No model API or cluster command runs. Input is the
hand-written `data/fixtures/m4/routing_synthetic.json`: two tasks, six candidate
estimates and three budget variants (5, 9 and 11 synthetic credits).
Costs and quality scores are invented test values, not prices, token counts,
billed costs or measured diagnostic accuracy. The request explicitly selects
the prototype `max_quality` objective; the TAF does not specify that objective.

The base commit is `9db46b3d7dbd6a0ba872d1cf3303ca58a3203446` (merged W3-03).
The measured W3-05 source was **uncommitted**. This is not clean-commit evidence.
`results/config.json` records the dirty paths, input/source SHA-256 hashes,
command, environment, solver timeout and dependency versions. Exact measured
router/runner sources and the dependency file are preserved under
`results/source_snapshot/`, and the exact input is `results/request.json`.
The source snapshots, rather than the base commit alone, identify this prototype.

## Command and reproduction

From the repository root with project dependencies installed:

```powershell
python -m argus.orchestration.router_benchmark data/fixtures/m4/routing_synthetic.json --budgets 5 9 11 --repetitions 20 --output-dir experiments/2026-10-17_m4_w3_05_offline_router_reproduction/results
```

Use a fresh output path: the runner rejects any existing directory. It records
actual invocation arguments; the recorded run's exact interpreter path is in
`results/config.json`. That run used bundled Python 3.12.14 with repository `src`
and existing `.venv/Lib/site-packages` on `PYTHONPATH`, because the local venv
launcher points to an unavailable interpreter. No dependency was added.

To reproduce this exact source after code changes, copy the preserved
`source_snapshot/` files into a separate checkout at the recorded base commit,
use `results/request.json` as input, and write to a new directory. Preserve the
original evidence. Plan choices should reproduce; latency depends on the host.

## Results

Each case has one separately recorded first call, one warmup, then 20 measured
calls: 60 repeated observations in total. Only the first case's first call is
the first route call in the process. Imports are excluded. Timings include
request validation, Z3 context creation, encoding and optimization. Per-case
medians are descriptive measurements on this Windows environment, not targets.

| Budget | Status | Selected cost | Selected quality sum | Repeated median (ms) |
|---:|---|---:|---:|---:|
| 5 | infeasible | n.a. | n.a. | 12.2524 |
| 9 | optimal | 8 | 175 | 16.8975 |
| 11 | optimal | 11 | 188 | 16.1579 |

An infeasible plan has an empty assignment and zero-valued total fields by the
local interface; zero is not the cost of a successful solution. Budget 9 selects
`fixture-frontier-a` for diagnosis and `fixture-low-b` for parsing. Budget 11
selects `fixture-frontier-b` and `fixture-low-b`. Deliberately cheaper and
higher-scoring wrong-layer candidates remain ineligible.

Raw per-call measurements are in `results/timings.csv`, exact assignments are in
`results/plans.json`, and per-case timing summaries are in `results/summary.json`.
This small synthetic test does not establish scaling, API savings, model quality
or SRE benchmark performance. No frontier-only baseline was measured in this run.

## Remaining work

Agree on real task schemas, model identities, prices, cost conversion, budget,
quality estimates and policy. Connect model adapters and incident accounting,
then implement and test the agreed timeout/fallback behavior. Keep every cluster
write on the existing W3-03 gate path. Provider integration is not claimed by
this experiment.

## Local validation

The focused M4 routing, measurement and W3-03 integration selection passed 99
tests. The available broader suite passed 350 tests, with one platform skip and
one deselected test (`test_timeout_returns_no_result`, the previously documented
Windows hang). The optional M3 evaluation module
`tests/unit/safety/test_evaluate.py` could not collect because SciPy is absent in
this environment; the broader run explicitly excluded that file. A full-suite
pass is not claimed. Ruff lint, formatting and `git diff --check` passed.

Tests compare optimal plans with independent exhaustive enumeration, including
both configured objectives, shared budgets, zero-cost cases, deterministic ties,
TAF eligibility, invalid inputs and solver failures. Measurement tests verify
raw timing aggregation, hashes, exact snapshots, repeatability and refusal to
overwrite evidence. No new CI result is claimed.

AI assistance: Codex produced the offline router, validation, exhaustive-search
comparison tests, latency runner, synthetic fixture and documentation, then ran
pytest, Ruff and this measurement. Raw outputs were generated by the runner and
were not edited by hand.
