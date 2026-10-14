<!-- Local replacement draft for PR #18; not posted to GitHub. -->

## What and why

M4 now passes `TelemetryBatch.alert_time` unchanged to M1 through
`CompressedTelemetry`, including omitted and explicit null cases. Existing
JSON-encoded TSV behavior, default JSON `original_size` semantics, fields,
exact values/types, duplicate multiplicities and record order are preserved.
M4 specifications use the flat function-document layout. The M1 owner approved
the one-line ingest docstring path correction in the review.

The W2-08 experiment runner now accepts detached HEAD and branches without an
upstream, recording absent Git references as null. A clean working tree and a
resolvable source commit remain required; existing evidence cannot be overwritten.

## Planner task and byte evidence

W2-08 remains incomplete. The input is one hand-written synthetic CART_ADDR
scenario, not recorded/live telemetry: 27 records (8 metrics, 9 logs, 6 spans,
4 Kubernetes records).

- Main baseline: compact JSON, 4,438 UTF-8 bytes; TSV, 3,746 bytes; **15.59% reduction**.
- Secondary baseline: default JSON, 4,798 UTF-8 bytes; **21.93% reduction**.
- Both JSON baselines serialize records only with `ensure_ascii=False`, no
  added newline. Compact uses `separators=(",", ":")`; default uses Python defaults.
- TSV includes the shared header, JSON cells, quoting, tabs and CRLF rows.
- The saved run records clean source commit
  `789f7f1398854a4cc827175f62854b7f0510d336`. Its source matches the reviewed head.
  Original results remain intact; fixture copies and dirty-source patches were
  removed by the earlier review fix. Fixture/provenance hashes identify the
  Windows CRLF checkout, while Git stores equivalent LF JSON blobs.
- The later runner fix changes Git metadata collection only. Reproduction on
  detached HEAD requires that fix; new runs record their actual committed SHA.

See [experiment notes](../experiments/2026-10-13_m4_contract_v1/NOTES.md).
All payloads were independently recomputed from the actual fixture and matched
the saved bytes and Git blobs. No token savings, RCA accuracy or general benchmark
performance is claimed.

## Validation

- 36 targeted runner/M4/M1/pipeline tests passed. The detached regression fails
  against the original runner at the reported upstream query and passes with the fix.
- Five runner cases cover detached HEAD, branches with/without upstream, and
  tracked/untracked dirt. Successful runs compare all summary keys and payload
  bytes and verify overwrite rejection.
- Broader Windows suite: 234 passed, 1 skipped, 1 deselected, excluding the known
  `test_timeout_returns_no_result` hang, with a 60-second external bound.
- Ruff lint and formatting pass. Remote PR head `c0db9bf` has passing checks;
  local changes have not been pushed and have no CI result.

The reviewer's 277-test Linux merge-with-main result was not independently repeated.
Default demo-fixture migration remains separate. Further team review, broader
samples and agreed token measurement rules remain outstanding. No dashboard,
shared-contract changes or compressor changes were added for the latest review.

## AI assistance

Codex inspected instructions and all PR reviews/discussions, reproduced the
reported error, checked source provenance and exact payloads against Git, and
generated the metadata fix, regression tests and documentation. Existing raw
evidence was retained without manual edits or relabelling.
