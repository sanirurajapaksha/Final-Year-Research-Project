# Minimal F1 fixture run

Date: 2026-10-10
Task: W1-09
Owner: Nethmi Herath
Status: Pending team review

This run used `.venv\Scripts\python.exe` to load
`data/fixtures/telemetry_sample.json` through `TelemetryBatch` and call the
actual `compress()` function. The input is one hand-written illustrative
fixture with three records. It is not live telemetry or a benchmark.
No model was used and no cluster command was executed.

The exact command, Python details, and base commit are in `config.json`.
The implementation has uncommitted changes, so the base commit alone does
not identify the code used. `run.py` records how the evidence was generated.
For a later run, copy the script into a new run folder; do not overwrite or
edit these raw results by hand.

Original reproduction command, run from the repository root:

```powershell
.venv\Scripts\python.exe experiments/2026-10-10_m4_minimal_f1/run.py
```

Use the copied script's path for a later run to keep these results intact.

After merging the package rename from `main`, `run.py` imports `argus`.
The recorded results and configuration still describe the original run.

## Results

- `results/telemetry_sample.tsv`: actual TSV bytes returned by `compress()`.
- `results/summary.json`: one sample, three records, TSV output, 241 original
  UTF-8 bytes, and 228 output UTF-8 bytes. It also records the exact original
  serialization convention. The original size covers serialized records
  only, not the entire fixture file.
- `results/checks.json`: exact check commands and exit codes.
- `results/pytest.stdout.txt`: retained raw test output, including the
  test-file breakdown. Empty check outputs were removed. The two Ruff
  output files were removed because their full results are recorded below
  and their commands and exit codes remain in `results/checks.json`.

Local checks: 30 tests passed in 0.10 seconds; Ruff check passed; Ruff format
check reported 53 files already formatted; `git diff --check` passed.
All four check commands returned exit code 0. CI status has not been verified.

The TSV is smaller for this fixture only. This run does not establish token
savings, benchmark performance, or root cause analysis accuracy. TSV is not
assumed to be smaller for other inputs.

M1 format agreement, shared contract decisions, and the complete W1-09
acceptance checklist still need team confirmation. F2 remains planned work.
