# M1: System Context Acquisition & Observation Layer

**Owner:** Minidu Weerasinghe

**Role in the flow:** M4's compressed telemetry → **M1** → Semantic Context Object → M4 → M2.

**Entry point:** `service.build_context(CompressedTelemetry) -> SemanticContext` (stub for now).

**Planned work** (from the proposal and the PP1 plan; yours to confirm or replace):
- Function 1: telemetry ingestion and a variance-based noise filter, producing an anomaly set.
- Function 2: Service Dependency Graph builder (e.g. from Jaeger spans) and the Semantic Context Object.
- Metrics: context recall, noise-reduction ratio, generation latency.

**Internal layout:** up to you. Add files here (e.g. `ingest.py`, `noise_filter.py`, `sdg.py`) and put tests in `tests/unit/context/`.
