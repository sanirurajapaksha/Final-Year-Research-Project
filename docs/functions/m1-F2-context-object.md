# Function spec: M1 F2 – Service Dependency Graph and Semantic Context Object

Status: specified, not implemented. Planned for W3-04; `build_context()` must be callable by Wed 14 Oct.

| Field | |
|---|---|
| Name | F2: Service Dependency Graph (SDG) and Semantic Context Object (`service.build_context`) |
| Owner | Weerasinghe W.P.M.T (Minidu) |
| Input | `CompressedTelemetry` from M4, including `alert_time`. Internally: F1's typed telemetry (spans, k8s entities) and F1's anomaly set. Test data: `data/fixtures/m1/scenario_01/` (synthetic), plus further hand-written scenarios; a dev-cluster pods snapshot when available |
| Processing logic | 1. Run F1 (decode, validate, Stage 1). 2. Build a directed graph of services from CLIENT→SERVER span hops in `[alert_time − Δ, alert_time]`. 3. Mark failing services: spans with an error status (`otel_status_code` ERROR, HTTP 5xx, gRPC ≠ 0), plus the **callee of a failed CLIENT span** (a crashed callee may emit no span at all). 4. Failing path = failing services and their callers up to the entry point. 5. Stage 2: keep an anomaly only if its service is on the failing path; prune the rest as ambient noise. 6. If traces are too sparse, fall back to a static topology (`topology.json`) and set `fallback_used`. 7. Annotate nodes with k8s state. 8. Convert to plain JSON and return |
| Output | `SemanticContext` (contract model): `kept_signals`, `symptoms`, `nodes`, `dependencies` (caller, callee), `failing_services`, `entry_point`, `fallback_used`, `strategy`. Pruned signals, raw counts and timings stay in an M1-internal report for experiments, not in the contract |
| Dependencies | F1; contract v1; `networkx` (approved by the team lead on 11 Oct; exact pin added in the F2 PR; used only inside M1) |
| Test evidence | Planned: `tests/unit/context/test_sdg.py`, `test_isolator.py`, `test_service.py`. Happy paths: CART_ADDR keeps cart and frontend signals and prunes the product-catalog memory spike and kube-system noise. Failure paths: sparse traces → fallback; cyclic calls; empty anomaly set; spans outside the alert window |

## Context strategies
`build_context` takes a `strategy`, so one evaluation harness can compare context strategies.
- **Before PP1:** `raw`, `stage1`, `failing_path`.
- **After PP1:** `top_k`, `one_hop`, `time_window` and `failing_path_k8s`.

## Objective → function → metric → evidence

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Give the diagnoser a small context that still contains the fault | Prune Stage 1 anomalies that are off the failing call path, and describe the topology | Context recall (fault entities in the context / fault entities in ground truth), at service and evidence level; NRR; false-prune rate; T_synth (median, compute time reported separately from fetch time), each with *n* | Planned: `experiments/2026-10-15_m1_*/results/` | `raw` and `stage1` strategies on the same scenarios | PP1: synthetic scenarios, *n* stated. After PP1: SREGym-Lite drills and RCAEval RE2 |
