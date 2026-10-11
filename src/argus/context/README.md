# M1: System Context Acquisition & Observation Layer

**Owner:** Minidu Weerasinghe

**Role in the flow:** M4's compressed telemetry → **M1** → Semantic Context Object → M4 → M2.

**Entry point:** `service.build_context(CompressedTelemetry) -> SemanticContext` (stub until F1 and F2 are wired in).

**Functions** (specs in `docs/functions/`):
- **F1, telemetry ingestion and Stage 1 noise filter** (`m1-F1-telemetry-noise-filter.md`): decode M4's TSV, validate records against the contract, and keep signals that cross threshold predicates. The output is an anomaly set.
- **F2, Service Dependency Graph and Semantic Context Object** (`m1-F2-context-object.md`): build the service graph from spans, prune anomalies that are off the failing call path (Stage 2), and return the Semantic Context Object.
- **Metrics:** noise-reduction ratio, context recall, false-prune rate, and generation latency (T_synth).

**Layout:**

| File | What |
|---|---|
| `ingest.py` | F1: M4 TSV → record dicts → typed models (`ParsedTelemetry`) |
| `filters.py` | F1: Stage 1 threshold predicates → `list[AnomalySignal]` |
| `service.py` | Public entry point `build_context` (stub) |
| `__main__.py` | Demo: `python -m argus.context [telemetry.json]` prints the anomaly set |

**Try it:** `python -m argus.context` runs F1 on `data/fixtures/m1/scenario_01/telemetry.json`. It's a hand-written, synthetic CART_ADDR scenario, and its labels are in `ground_truth.json`.

**Tests:** `tests/unit/context/`, and `tests/integration/test_m1_reads_m4_output.py` for reading M4's real output.
