# M1: System Context Acquisition & Observation Layer

**Owner:** Minidu Weerasinghe

**Role in the flow:** M4's compressed telemetry → **M1** → Semantic Context Object → M4 → M2.

**Entry point:** `service.build_context(CompressedTelemetry) -> SemanticContext`. The default `strategy="failing_path"` runs F1 and then F2 (service graph and Stage 2 pruning); `strategy="stage1"` stops after F1. `service.build_report(...)` returns the same context plus the M1-internal results (the Stage 1 set, pruned signals with reasons, the graph) for experiments and the UI.

**Functions** (specs in `docs/functions/`):
- **F1, telemetry ingestion and Stage 1 noise filter** (`m1-F1-telemetry-noise-filter.md`): decode M4's TSV, validate records against the contract, and keep signals that cross threshold predicates. The output is an anomaly set.
- **F2, Service Dependency Graph and Semantic Context Object** (`m1-F2-context-object.md`): build the service graph from spans, prune anomalies that are off the failing call path (Stage 2), and return the Semantic Context Object.
- **Metrics:** noise-reduction ratio, context recall, false-prune rate, and generation latency (T_synth).

**Layout:**

| File | What |
|---|---|
| `ingest.py` | F1: M4 TSV → record dicts → typed models (`ParsedTelemetry`) |
| `filters.py` | F1: Stage 1 threshold predicates → `list[AnomalySignal]` |
| `metrics.py` | Noise-reduction ratios (simple and labelled) and false-prune rate |
| `sdg.py` | F2: alert window, service dependency graph from spans, failing services, entry point, failing path |
| `isolator.py` | F2 Stage 2: keep anomalies on the failing path; prune the rest with a reason |
| `service.py` | Public entry point `build_context` (and `build_report`): M4 TSV → F1 → F2 → `SemanticContext` |
| `report.py` | `report_data(ContextReport)`: the run as plain data for the dashboard (graph edges, failing path, every Stage 1 anomaly kept or pruned with its reason) |
| `__main__.py` | Demo: `python -m argus.context [telemetry.json]` prints the anomaly set |

**Try it:** `python -m argus.context` runs F1 on `data/fixtures/m1/scenario_01/telemetry.json`. It's a hand-written, synthetic CART_ADDR scenario, and its labels are in `ground_truth.json`.

**Dashboard:** the **M1 context** page of the team app (`python -m streamlit run src/argus/demo/app.py`, page file `src/argus/demo/pages/1_M1_context.py`). After the incident runs on the first page, it re-runs M1 on the same telemetry and shows the graph, the kept and pruned signals with reasons, and the context M2 receives.

**Results** (n = 1, synthetic):
- `experiments/2026-10-11_m1_stage1_nrr/`: Stage 1 alone.
- `experiments/2026-10-18_m1_stage2_failing_path/`: Stage 2 removes the 3 noise signals that Stage 1 keeps, with no evidence lost.

**Tests:** `tests/unit/context/`, `tests/integration/test_m1_reads_m4_output.py` for reading M4's real output, and `tests/integration/test_m1_page.py` for the dashboard page.
