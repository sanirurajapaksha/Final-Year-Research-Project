# Function spec: M1 F1 – Telemetry ingestion and Stage 1 noise filter

Status: complete for PP1 scope (W2-06). Wired into `service.build_context`, with the first noise-reduction ratio recorded on one synthetic scenario.

| Field | |
|---|---|
| Name | F1: Telemetry ingestion and Stage 1 noise filter (`ingest.decode_tsv`, `ingest.parse_records`, `filters.extract_anomalies`), reached through the public entry point `service.build_context(CompressedTelemetry) -> SemanticContext` |
| Owner | Weerasinghe W.P.M.T (Minidu) |
| Input | Telemetry records shaped like the contract's `TelemetryRecord` models (`metric`, `log`, `span`, `k8s`, chosen by `kind`). Two routes: M4's compressed TSV (`CompressedTelemetry.content`), or `TelemetryBatch.records` directly. Test data: `data/fixtures/m1/scenario_01/` (**hand-written, synthetic**, modelled on the Stratus CART_ADDR example: 27 records, labelled in `ground_truth.json`) |
| Processing logic | 1. Decode M4's TSV: header row, JSON cell per field, empty cell = missing field. 2. Validate every record into its typed model by `kind`; any invalid record raises `IngestError` (no silent drops). 3. Stage 1 predicates: metric above its threshold (`http_5xx_rate` > 0.05, `cpu_utilization` > 0.90, `memory_utilization` > 0.90); log severity ∈ {ERROR, CRITICAL, FATAL}; k8s status ∈ {CrashLoopBackOff, Error, OOMKilled} or restarts > 3. Thresholds are a `Thresholds` object so experiments can vary them. Spans are not Stage 1 input (F2 uses them) |
| Output | `list[AnomalySignal]` (contract model): service, source, name, value, timestamp, and an evidence string. Through `build_context`: a `SemanticContext` with `kept_signals`, readable `anomalies`, `services` and `strategy="stage1"`; telemetry that isn't in the contract v1 shape gives an empty context with the reason in `notes` |
| Dependencies | Contract v1 models (`argus.contracts`, PR for W2-01); M4's TSV format (`docs/functions/m4/F1.md`); Python standard library only |
| Test evidence | Unit: `tests/unit/context/test_ingest.py`, `test_filters.py`, `test_cli.py`, `test_metrics.py`, `test_service.py`. Cross-module: `tests/integration/test_m1_reads_m4_output.py` (M4's real `compress()` → M1 decode gives the same records and the same anomaly set). Demo: `python -m argus.context` |

**Happy-path tests:**
- `scenario_01` gives exactly the 8 Stage 1 signals listed in `ground_truth.json`.
- WARN logs, normal metrics and spans are dropped.
- Custom thresholds change the result.
- A crash-looping pod is flagged.
- The TSV round trip works, including a tab inside a value.
- `build_context` on M4's real output gives the 8 signals as `kept_signals`, and the context round-trips through JSON.
- Metrics on `scenario_01`: 21 in, 8 kept, 5 of 5 evidence kept.

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
- `build_context` on v0-shaped or malformed telemetry: an empty context with the reason in `notes`, not an exception.
- Metrics: undefined ratios (empty input, no noise) raise; impossible counts are rejected.

## Objective → function → metric → evidence

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Reduce the telemetry an LLM diagnoser must read, without losing the fault | Ingest all signal types and keep only threshold-crossing signals (Stage 1) | Noise-reduction ratio (1 − kept / raw, and labelled noise pruned / labelled noise), with *n* stated; false-prune rate | `experiments/2026-10-11_m1_stage1_nrr/` (n = 1, synthetic): NRR 0.619 (1 − 8/21), labelled NRR 0.813 (13/16 noise removed), false-prune rate 0 (5/5 evidence kept), median compute 0.48 ms | Raw telemetry (no filtering), as in direct ingestion | PP1: hand-written synthetic scenarios (label *n* and "synthetic" on the slide). After PP1: SREGym-Lite drills and RCAEval RE2 |

## Known limits of this slice
- Thresholds are first guesses, not tuned. They are reported with every result.
- k8s snapshots have no per-object timestamp, so a k8s signal uses the newest telemetry timestamp.
- *n* = 1 synthetic scenario, written alongside the filter. It is not recorded telemetry, because the dev cluster isn't up yet.
- The shared v0 fixture (`data/fixtures/telemetry_sample.json`) isn't in the contract v1 shape. `python -m argus` on it shows M1's "could not read" note. It moves to v1 together with M4.
- The context holds the Stage 1 set only. Stage 2 pruning and the graph fields (`nodes`, `failing_services`, `entry_point`) are F2 (W3-04).
