# Function spec: M1 F1 – Telemetry ingestion and Stage 1 noise filter

Status: minimal slice implemented (W1-06). Completion with the noise-reduction ratio is W2-06.

| Field | |
|---|---|
| Name | F1: Telemetry ingestion and Stage 1 noise filter (`ingest.decode_tsv`, `ingest.parse_records`, `filters.extract_anomalies`) |
| Owner | Weerasinghe W.P.M.T (Minidu) |
| Input | Telemetry records shaped like the contract's `TelemetryRecord` models (`metric`, `log`, `span`, `k8s`, chosen by `kind`). Two routes: M4's compressed TSV (`CompressedTelemetry.content`), or `TelemetryBatch.records` directly. Test data: `data/fixtures/m1/scenario_01/` (**hand-written, synthetic**, modelled on the Stratus CART_ADDR example: 27 records, labelled in `ground_truth.json`) |
| Processing logic | 1. Decode M4's TSV: header row, JSON cell per field, empty cell = missing field. 2. Validate every record into its typed model by `kind`; any invalid record raises `IngestError` (no silent drops). 3. Stage 1 predicates: metric above its threshold (`http_5xx_rate` > 0.05, `cpu_utilization` > 0.90, `memory_utilization` > 0.90); log severity ∈ {ERROR, CRITICAL, FATAL}; k8s status ∈ {CrashLoopBackOff, Error, OOMKilled} or restarts > 3. Thresholds are a `Thresholds` object so experiments can vary them. Spans are not Stage 1 input (F2 uses them) |
| Output | `list[AnomalySignal]` (contract model): service, source, name, value, timestamp, and an evidence string |
| Dependencies | Contract v1 models (`argus.contracts`, PR for W2-01); M4's TSV format (`docs/functions/m4/F1.md`); Python standard library only |
| Test evidence | Unit: `tests/unit/context/test_ingest.py`, `test_filters.py`, `test_cli.py`. Cross-module: `tests/integration/test_m1_reads_m4_output.py` (M4's real `compress()` → M1 decode gives the same records and the same anomaly set). Demo: `python -m argus.context` |

**Happy-path tests:**
- `scenario_01` gives exactly the 8 Stage 1 signals listed in `ground_truth.json`.
- WARN logs, normal metrics and spans are dropped.
- Custom thresholds change the result.
- A crash-looping pod is flagged.
- The TSV round trip works, including a tab inside a value.

**Failure-path tests:**
- Empty input.
- A TSV cell that isn't JSON.
- A TSV row with the wrong number of cells.
- A record with a missing field.
- An unknown `kind`.
- A metric exactly at its threshold.
- An unknown metric name.
- A k8s-only input with no timestamp.
- A missing fixture file.

## Objective → function → metric → evidence

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Reduce the telemetry an LLM diagnoser must read, without losing the fault | Ingest all signal types and keep only threshold-crossing signals (Stage 1) | Noise-reduction ratio (1 − kept / raw, and labelled noise pruned / labelled noise), with *n* stated; false-prune rate | `scenario_01`: 8 anomalies from 27 records; all 5 fault-relevant signals kept; 3 labelled noise signals remain for Stage 2 | Raw telemetry (no filtering), as in direct ingestion | PP1: hand-written synthetic scenarios (label *n* and "synthetic" on the slide). After PP1: SREGym-Lite drills and RCAEval RE2 |

## Known limits of this slice
- Thresholds are first guesses, not tuned. They are reported with every result.
- k8s snapshots have no per-object timestamp, so a k8s signal uses the newest telemetry timestamp.
- Not yet wired into `service.build_context`: the shared v0 fixture (`data/fixtures/telemetry_sample.json`) doesn't follow the contract v1 record shape. That happens once contract v1 is approved (W2-06).
