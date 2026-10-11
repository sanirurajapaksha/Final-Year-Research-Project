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

The portable command, Python details, and base commit are in `config.json`.
The implementation has uncommitted changes, so the base commit alone does
not identify the code used. `run.py` records how the evidence was generated.
For a later run, copy the script into a new run folder; do not overwrite these historical results.

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
- `results/checks.json`: portable check commands and original exit codes.
- `results/pytest.stdout.txt`: retained test output with its root path normalized, including the
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

## Review: path portability and saved TSV

Paths were normalized for portability after review. In `config.json` and
`results/checks.json`, the original local interpreter path was replaced with
`.venv/Scripts/python.exe`, relative to the repository root. In the saved
pytest output, only the `rootdir` path was replaced with `.`, and that
edited line uses an LF ending to pass the whitespace check. These command
and log texts are normalized evidence, not untouched raw logs. The original
Python version, base commit, source-state warning, results, exit codes,
30-test count, 0.10-second timing, and byte counts were preserved.
This limited path edit follows the review request; no experiment was rerun.
`run.py` now saves portable interpreter and script paths and normalizes local
root/interpreter paths in future saved check output. An interpreter outside
the repository is represented as `python`; run it in the same environment.

The saved TSV was read with `csv.reader(..., delimiter="\t")` and
`newline=""`, then every nonempty cell was decoded with `json.loads`.
All three restored records match the original fixture, including every
value's exact type. The column order is `kind`, `service`, `name`, `value`,
`message`, `object`, `reason`, matching first-seen fixture keys. The saved
UTF-8 payload is 228 bytes; the original records serialized with the
recorded JSON convention are 241 bytes. Both match `results/summary.json`.
The saved payload also matches the current compressor byte for byte.
The TSV and summary were left unchanged.

Triple quotes such as `"""metric"""` are expected: JSON first encodes the
string as `"metric"`; the TSV writer wraps that cell in quotes and doubles
its inner quotes. The CSV reader removes the outer quoting, and
`json.loads` restores the string. Empty TSV cells mean missing fields.
This confirms the saved sample is correct under the implemented draft
format. It does not mean M1 has approved this format or contract v1.

AI assistance: Codex inspected the evidence, compressor, tests and specs,
normalized path text, and checked the saved TSV and local checks. It did
not rerun the experiment or change shared contracts or dependencies.

Review checks used `.venv/Scripts/python.exe`: 31 tests passed in 0.15
seconds; Ruff check passed; Ruff format reported 54 files already formatted;
`python -m argus` returned 0 (M3 blocked the sample write and M4 executed
nothing). `git diff --check` passed after fixing the edited line ending.
These are new review checks, separate from the historical experiment checks.
