# M4 PP1 integration log

Owner: Nethmi Herath

Date: 2026-10-19

Plan: [PP1 M4 integration plan](m4-pp1-integration-plan.md),
M4 items 1, 2, 4, 5 and 6 (Planner task W3-08).

- Confirmed that merged PR #25 passes the supplied diagnoser into
  `process_diagnosis(..., feedback_handler=diagnoser)`. The regression test
  exercises both calls and checks that BLOCK verdicts reach that diagnoser.
- Replaced the M4 placeholder in the shared dashboard with compression,
  saved safety/executor handoffs, routing plans and fallback attempts.
- Added plain-data reporting under M4. Compression uses the shared demo's
  synthetic scenario_01 input. Safety rows use its saved session record.
- Routing is explicitly a scripted replay of that record's first diagnosis.
  It uses the real dispatcher but makes no provider calls or action handoffs.
  Costs, quality and deadlines are labelled synthetic/simulated.
- Kept one app, the existing entry point, the executor stub and shared contracts.
- Recorded the proposed future `run_function2` integration in M4's README.
  Real-provider dispatch is optional in this plan and remains deferred.

Validation: 629 tests passed and one platform-specific test was skipped across
two interpreter runs. The underlying Python interpreter passed 624 tests; five
experiment-runner tests needed the venv interpreter because their subprocesses
replace `PYTHONPATH`. Those five passed on retry. This avoids an existing Windows
venv-launcher hang in M3's solver-timeout test without changing M3. Repository
Ruff lint and format checks passed. The offline CLI completed without exceptions;
M3 blocked the patch without an API key as expected.
