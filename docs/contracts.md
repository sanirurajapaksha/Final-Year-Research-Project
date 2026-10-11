# Contracts between modules (draft v0)

The typed messages in `src/argus/contracts/` are a first draft for **contract v1**, which all four owners agree together (Planner task W2-01). Until then, change them freely, but in a PR that every affected owner sees.

| Model | From → to | File |
|---|---|---|
| `TelemetryBatch` | benchmark → M4 | `telemetry.py` |
| `TelemetryRecord` (`MetricSample`, `LogRecord`, `Span`, `K8sEntity`) | the shape of each `TelemetryBatch.records` entry; M1 validates them | `telemetry.py` |
| `CompressedTelemetry` | M4 → M1 | `telemetry.py` |
| `SemanticContext` (with `AnomalySignal`, `ServiceNode`) | M1 → M4 → M2 | `context.py` |
| `DiagnosisResult`, `Hypothesis`, `ProposedAction` | M2 → M4 (→ M3 for writes) | `diagnosis.py` |
| `SafetyVerdict`, `Z3Result`, `GateDecision` | M3 → M4; M3 → M2 on BLOCK | `safety.py` |
| `ExecutionResult` | M4's execution handler | `execution.py` |

## Rules
1. **Commands are byte-exact.** `ProposedAction.command` is never compressed, trimmed or rewritten after M2 creates it. M3 checks exactly the string that will run.
2. **M3's raw solver result and its decision are separate fields.** `z3_result` is Z3's answer on the negated safety formula; `decision` is APPROVE or BLOCK.
   - `unsat` → APPROVE
   - `sat` → BLOCK, with the counterexample
   - `unknown`, timeout or error → BLOCK
3. **Naming.** Reports describe M3's verdicts as SAT (safe) and UNSAT (unsafe). The code never uses those words for the decision, so the safe verdict can't be confused with Z3's raw `sat`.
4. **Counterexamples go back to M2** through `diagnose(..., feedback=[...])`.
5. **Changing a contract:** open a PR that touches `contracts/` and get approval from every owner whose module sends or receives that model.
6. **Telemetry records are plain dicts with a `kind`.** `TelemetryBatch.records` stays `list[dict]`, so M4 can convert it to TSV without knowing the record types. Each dict has the fields of one `TelemetryRecord` model, chosen by its `kind`. M1 validates each decoded record with `TypeAdapter(TelemetryRecord)`.
7. **Telemetry fields M1 relies on survive compression unchanged.** After decoding M4's TSV, `json.loads` of each cell gives back the original value and type, and column names are unchanged. Missing fields are empty cells; `null` and `""` stay distinct (see `docs/functions/m4/F1.md`). `CompressedTelemetry.alert_time` is copied unchanged from `TelemetryBatch.alert_time`.
8. **`SemanticContext` is plain JSON.** No graph-library objects cross the boundary: dependencies are `(caller, callee)` pairs and nodes are `ServiceNode`s. Pruned signals, raw counts and timings stay inside M1.

## Telemetry records (proposed for v1)

Every record has `kind` and `service`. Send timestamps as ISO 8601 UTC strings.

| `kind` | Model | Fields |
|---|---|---|
| `metric` | `MetricSample` | `name`, `labels`, `timestamp`, `value` |
| `log` | `LogRecord` | `severity` (`DEBUG`, `INFO`, `WARN`, `ERROR`, `CRITICAL`, `FATAL`), `message`, `timestamp` |
| `span` | `Span` | `trace_id`, `span_id`, `parent_span_id`, `operation`, `span_kind` (`CLIENT`, `SERVER`, `INTERNAL`, `PRODUCER`, `CONSUMER`), `start_time`, `duration_ms`, `otel_status_code` (`OK`, `ERROR`, `UNSET`), `http_status_code`, `grpc_status_code` |
| `k8s` | `K8sEntity` | `name`, `namespace`, `resource` (e.g. `Pod`, `Deployment`), `status`, `restart_count`, `replicas` |

The span's CLIENT/SERVER field is `span_kind` because `kind` names the record type. M1 draws dependency edges from CLIENT→SERVER hops and treats the callee of a failed CLIENT span as failing, which is why `span_kind`, `start_time` and the status codes must be kept.

`data/fixtures/telemetry_sample.json` still uses the v0 shape (an `event` record, no timestamps). It will move to these models once the owners approve them, together with M4's tests and evidence that read it.
