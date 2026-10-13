# M4 contract v1: byte-only evaluation

Date: 2026-10-13
Task: W2-08
Owner: Nethmi Herath
Status: Byte evaluation recorded; W2-08 remains incomplete.

## Input and scope

Input: `data/fixtures/m1/scenario_01/telemetry.json`. Its source text and
`ground_truth.json` identify it as one hand-written synthetic CART_ADDR
scenario. It is not recorded or live telemetry. All metric, log, span and
Kubernetes records are included; M4 does no filtering or row selection.
No model or cluster command is used.

## Reproduction

From the repository root, after installing the project's existing dependencies:

```powershell
.venv\Scripts\python.exe experiments/2026-10-13_m4_contract_v1/run.py --output-dir experiments/2026-10-13_m4_contract_v1_reproduction
```

On Linux/macOS, use `.venv/bin/python` instead. The initial run used the same
script without `--output-dir`. `config.json` records its portable command,
Python/platform, input hashes, source commit, branch, upstream and dirty state.
The commit alone does not identify the implementation: existing M4 changes
were uncommitted. Source file hashes, the runner hash and the generated
`results/source_changes.patch` identify the evaluated state. Use that state
when reproducing; changed code or input makes a new evaluation.
The script refuses to overwrite an existing config or results directory.

## Measurements and preservation

`results/summary.json` contains calculated sample/record counts, per-kind
counts, exact UTF-8 byte sizes and byte reduction percentage. No measured
counts or sizes are hard-coded in the runner.

The baseline is exactly `json.dumps(batch.records, ensure_ascii=False)` with
all other Python defaults, encoded as UTF-8 with no added newline. It excludes
batch metadata and fixture-file formatting. The TSV is the exact compressor
output, including its shared header, JSON cells, quoting, tabs and CRLF rows.
Both payloads are saved as bytes in `baseline.json` and `telemetry.tsv`.
Byte reduction is `100 * (input_bytes - output_bytes) / input_bytes`.

The runner validates the original records through M1, then checks every decoded
record recursively for exact JSON value/type, field names, multiplicity and
original order. It verifies one shared header, one row per record, unchanged
input and preserved `alert_time`. The summary reports exact duplicate counts;
repeated messages with different timestamps are not exact duplicate records.
Targeted M4 tests separately cover actual duplicates and optional/default cases.

## Verification and limits

`results/checks.json` records actual exit codes for targeted M4 unit tests,
M1/M4 integration tests, Ruff lint/format checks and `git diff --check`.
Nonempty stdout logs are preserved unchanged. Five zero-byte files were
removed after inspection: targeted M4/M1 stderr, Ruff lint stderr, Ruff format
stderr, and both git diff check streams. The check index now records those
streams as empty (with byte count and hash), rather than linking to missing
files. Exit codes are unchanged. This is summarized evidence, not a new run.
The runner still writes the original eight streams when reproducing.

The sole machine-specific absolute path is the rootdir in the raw targeted
pytest log. It is retained as original diagnostic context; no nonempty log
was normalized. Configuration and reproduction commands are portable.
Local `.gitattributes` preserves result bytes, significant TSV/patch whitespace
and the original runner bytes through Git checkout. No payload was rewritten.

The full suite is still blocked by
`tests/unit/safety/test_sandbox.py::test_timeout_returns_no_result` on Windows.
A prior bounded investigation stopped it after 15 seconds and found a worker
alive after launcher termination, with no M4 modules loaded. This evaluation
does not rerun it or claim a full-suite pass.

The default demo fixture `data/fixtures/telemetry_sample.json` is unchanged
and remains incompatible with contract v1: the metric lacks `timestamp`,
the log lacks `timestamp` and `severity`, and `event` is unsupported.
Historical experiments are unchanged.

PP1 may report UTF-8 bytes now. Model/tokenizer selection is not a blocker for
byte evaluation. Tokens were not counted; token savings remain pending.
This one synthetic sample does not establish RCA accuracy or general benchmark
performance. No dependencies, M3 code or shared contracts were changed.

PR preparation checks on 2026-10-13: 31 targeted M4/M1 and pipeline tests
passed in 0.12 seconds. Ruff lint and format checks passed (85 files formatted);
`git diff --check` passed. This is a later review, separate from the original
29-test measurement run. The test records now set `kind` explicitly when
optional fields are omitted. The measured compressor code and payloads are
unchanged; original source hashes and the source patch retain the run state.

Remaining W2-08 work: team review of the byte evidence and acceptance checklist,
more agreed samples for broader byte claims, coordinated demo-fixture migration,
and full-suite verification after M3 fixes its timeout. Token evaluation is
separate later work after model/tokenizer and measurement rules are agreed.

AI assistance: Codex inspected the existing scenario and contracts, created the
runner and notes, and ran the recorded checks. Payloads, measurements, input
snapshots, config, hashes and source patch are unchanged program output.
During PR review, Codex removed only inspected zero-byte logs and generated
the summarized check index above. The measured code was dirty; keep the
source patch even though later documentation paths and test details changed.
