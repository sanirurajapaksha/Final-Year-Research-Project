# Function spec: M4 F1 — Telemetry compression

Status: Minimal F1 slice and contract v1 integration implemented. M1 format and field preservation were confirmed on 2026-10-11. W2-08 remains incomplete; token counting and savings await model/tokenizer selection.
Owner: Nethmi Herath

| Field | Description |
|---|---|
| Name | F1: Telemetry Compression |
| Owner | Nethmi Herath |
| Input | `TelemetryBatch`; initial test data is `data/fixtures/telemetry_sample.json`, a hand-written sample, not live telemetry. |
| Processing logic | Build columns in first-seen order, JSON-encode present values, and write TSV using `csv.writer`. Keep missing fields separate from null and empty strings. Measure UTF-8 bytes. |
| Output | `CompressedTelemetry` with TSV content and original and output sizes in UTF-8 bytes, not tokens. |
| Dependencies | Existing shared models and Python's standard library. M1 format and field preservation confirmed; contract v1 `alert_time` integration implemented. |
| Test evidence | Local checks are listed below. Unit tests: `tests/unit/orchestration/test_service.py`. Pipeline tests: `tests/integration/test_pipeline.py`. Remote PR #18 checks passed on 2026-10-14 for head `0d91dac`; the local review commits have not been pushed. |

## Input
TelemetryBatch containing metrics, logs, spans and Kubernetes records, with optional `alert_time`.
Initial sample: data/fixtures/telemetry_sample.json

## Processing
1. Read `TelemetryBatch.records` without changing the input.
2. Build columns from every record key, in the order each key first appears.
3. Write one header row and one row per record using Python `csv.writer`
   with a tab delimiter and its default quoting and CRLF row endings.
4. Encode each present cell with `json.dumps(value, ensure_ascii=False)`.
   This keeps JSON values and types, including numbers, booleans, lists,
   nested objects, strings and null values.
5. Write an empty cell for a missing field. After reading with `csv.reader`,
   a missing cell is empty, a null cell contains `null`, and an empty string
   cell contains `""`. Skip missing cells and use `json.loads` on present cells
   to recover the records. JSON escapes tabs and newlines inside values;
   CSV quoting also handles tabs and newlines in column names.
6. For an empty list, return an empty payload. For records that are empty
   dictionaries, keep one empty header row and one empty row per record.
   A reader must keep these rows to preserve the number of records.
7. Measure `original_size` from the UTF-8 bytes of
   `json.dumps(batch.records, ensure_ascii=False)`. Measure `compressed_size`
   from the UTF-8 bytes of the TSV payload. These are byte counts, not token
   counts. TSV can be larger than the original JSON for small inputs.
8. Copy `batch.alert_time` unchanged to `CompressedTelemetry.alert_time`,
   including `None` when omitted or explicitly null under contract v1.

This slice accepts JSON-compatible values. A value that JSON cannot encode
raises `TypeError`; it is not silently converted into a string.

Deduplication, row selection, token counting and model routing are not
implemented in this slice. `execute()` remains the existing stub and does
not run commands.

## Output
CompressedTelemetry containing the TSV payload.
The function signature and existing shared models are unchanged.

## Dependencies
- Existing TelemetryBatch and CompressedTelemetry models.
- Confirmed: M1 format and field preservation agreement from Minidu
  Weerasinghe, received on 2026-10-11, as recorded below.
- Contract PR #11 is merged. Both telemetry models support optional
  `alert_time`; M4 now copies it unchanged. Shared contracts are unchanged.

## M1 confirmation for W1-09

Confirmation source: Minidu Weerasinghe (M1), received on 2026-10-11.

Confirmed format:

- Current JSON-encoded TSV cells are accepted.
- Use one shared header; no per-type headers are required.
- An empty cell means missing. Null and empty string remain distinct.
- For each present cell, `json.loads(cell)` must return the original value
  and exact type, including values inside lists and dictionaries.
- Column names must remain unchanged.

Fields to preserve when present:

| Record type | Fields |
|---|---|
| All records | `kind`, `service` |
| Metric | `name`, `labels`, `value`, `timestamp` |
| Log | `severity`, `message`, `timestamp` |
| Span | `trace_id`, `span_id`, `parent_span_id`, `operation`, `span_kind`, `start_time`, `duration_ms`, `otel_status_code`, `http_status_code`, `grpc_status_code` |
| K8s | `name`, `namespace`, `resource`, `status`, `restart_count`, `replicas` |

Every typed record carries `kind` under contract v1.
Timestamps are ISO 8601 UTC strings. These are contract expectations;
this documentation change adds no required-field validation.

The confirmed M4 rule is to preserve every record, duplicate, field and
original record order. Do not drop, merge, deduplicate or select rows.
Noise pruning belongs to M1 and affects its evaluation. The field list does
not authorize removing other fields. Use one shared header for all records.

## Contract v1 integration

Contract PR #11 added optional `alert_time: datetime | None = None` to
`TelemetryBatch` and `CompressedTelemetry`. M4 copies `batch.alert_time`
unchanged. Unit tests cover a supplied time, explicit null, and the omitted
default, with empty and nonempty records. Mixed metric, log, span and Kubernetes
tests verify all contract fields, defaults and omitted optional fields, exact
decoded JSON values/types, unchanged field names, duplicates and record order.
Existing tests still cover byte sizes and missing/null/empty distinctions.
`tests/integration/test_m1_reads_m4_output.py` checks M1 reads the real TSV.
M4 adds no record validation and does not change shared contracts.

PP1 measurements use UTF-8 bytes for `original_size` and `compressed_size`.
Token counting and savings remain pending model/tokenizer selection and the
measurement decisions in [token-counting proposal](m4-token-counting-proposal.md).
No dependencies were added and historical experiment evidence is unchanged.

## Test evidence
Actual test file paths:

- `tests/unit/orchestration/test_service.py`: sample and edge-case round trips,
  recursive value and exact type checks inside lists and dictionaries,
  UTF-8 byte sizes, and a failure case for a value JSON cannot encode.
- `tests/integration/test_pipeline.py`: existing pipeline safety checks.
  These do not prove live execution or completed model routing.

Remote PR #18 checks passed on 2026-10-14 for head `0d91dac`; the local review commits have not been pushed. The results below are local checks only.

Verified on Windows on 2026-10-10 using `.venv\Scripts\python.exe`:

- `python -m pytest`: 30 passed in 0.08 seconds, including 17 orchestration
  tests. Tests cover the sample fixture, first-seen columns, different fields,
  recursive value and type round trips, including nested `True`, `1`, and
  `1.0`, missing fields versus null and empty strings,
  tabs, newlines and quotes, empty input and empty dictionaries, UTF-8 byte
  sizes, and rejection of values that JSON cannot encode.
- `python -m ruff check .`: all checks passed.
- `python -m ruff format --check .`: 52 files already formatted.
- `python -m sre_agent`: exit code 0. The demo printed the M1 and M2 stub
  results, M3 blocked the sample write action, and M4 did not execute the read
  action.
- `git diff --check`: passed with no whitespace errors.

## W2-08 contract integration checks

Checked on Windows on 2026-10-13 using `.venv\Scripts\python.exe`:

- Full `python -m pytest`: collected 231 tests, then stalled in the existing
  `tests/unit/safety/test_sandbox.py::test_timeout_returns_no_result` test.
  The run was stopped; the full suite is not reported as passing.
- `python -m pytest -k "not test_timeout_returns_no_result"`: 229 passed,
  1 skipped (Unix-only memory cap), 1 deselected in 5.13 seconds.
- M4 unit tests plus `tests/integration/test_m1_reads_m4_output.py`:
  29 passed in 0.08 seconds after the final test changes.
- `python -m ruff check .`: all checks passed.
- `python -m ruff format --check .`: 83 files already formatted.
- `python -m argus`: exit code 0. M1 reported that the existing sample
  metric lacks required `timestamp`; M3 blocked the write and M4 executed
  nothing. The fixture was not changed in this M4-only task.
- `git diff --check`: passed with no whitespace errors.

These checks do not establish token savings or complete W2-08. Historical
experiment files and the earlier test evidence above remain unchanged.

PR preparation checks on 2026-10-13: 31 targeted M4/M1 and pipeline tests
passed in 0.12 seconds; Ruff lint passed, Ruff format reported 85 files
formatted, and `git diff --check` passed. The known full-suite timeout was
not rerun. Default demo-fixture migration is still pending.

## Objective -> function -> metric -> evidence

The [contract v1 byte evaluation](../../experiments/2026-10-13_m4_contract_v1/NOTES.md)
records a byte-only evaluation on one synthetic sample with 27 records:
4,438 compact JSON UTF-8 bytes and 3,746 TSV UTF-8 bytes, a 15.59% reduction.
The secondary default JSON baseline is 4,798 bytes, a 21.93% reduction.
The compressor retains default JSON `original_size` semantics. All
records, fields, exact decoded values/types and order match; alert time is
preserved. The sample has no exact duplicate records; unit tests cover them.
No token savings, RCA accuracy or general benchmark performance is claimed.
PP1 byte evaluation can proceed without selecting a tokenizer.

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Preserve JSON records while converting them to TSV | `compress()` | Record values, field presence, and exact types after reading TSV back | `tests/unit/orchestration/test_service.py`: sample, nested values, and edge-case round trips | Original input records | Compare every restored value and type, including nested lists and dictionaries |
| Report input and output sizes correctly | `compress()` | UTF-8 byte counts of serialized input JSON and output TSV | `tests/unit/orchestration/test_service.py`: empty input and UTF-8 size tests | `json.dumps(batch.records, ensure_ascii=False)` encoded as UTF-8 | Compare reported sizes with byte lengths; do not treat them as token counts |
| Evaluate later compression work | Planned work, not part of this slice | Measures and targets remain draft | No evaluation results for later compression work | Pending team decision | Use the confirmed M1 field preservation rules; agree on data and remaining evaluation rules with the team before measuring savings |

## Remaining work for W1-09

This document records only the first minimal F1 slice. W1-09 is not marked
complete. Its full acceptance checklist was not found in the repository,
so it still needs to be checked against the team task record. M1 format
and field preservation are confirmed by Minidu Weerasinghe above.
The `alert_time` contract integration is implemented. Other unresolved team
contract and evaluation decisions remain pending. The token-counting proposal
belongs to W2-08 and remains supporting documentation. The byte evaluation
is recorded; W2-08 is not marked complete.
Later compression and routing work must follow the agreed task scope;
it is not included in this implementation.
