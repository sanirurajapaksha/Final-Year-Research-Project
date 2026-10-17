# Function spec: M1 F2 – Service Dependency Graph and Semantic Context Object

Status: W3-04 part 1 implemented: steps 1–5, 7 and 8, with the `stage1` and `failing_path` strategies. Not built yet: the static-topology fallback (step 6) and the `raw` strategy.

| Field | |
|---|---|
| Name | F2: Service Dependency Graph (SDG) and Semantic Context Object (`service.build_context`) |
| Owner | Weerasinghe W.P.M.T (Minidu) |
| Input | `CompressedTelemetry` from M4, including `alert_time`. Internally: F1's typed telemetry (spans, k8s entities) and F1's anomaly set. Test data: `data/fixtures/m1/scenario_01/` (synthetic), plus further hand-written scenarios; a dev-cluster pods snapshot when available |
| Processing logic | 1. Run F1 (decode, validate, Stage 1). 2. Build a directed graph of services from spans in `[alert_time − Δ, alert_time]` (Δ = 5 min by default; all spans if `alert_time` is missing). An edge (caller, callee) comes from a span whose parent span is in a different service. 3. Mark failing services: spans with an error status (`otel_status_code` ERROR, HTTP 5xx, gRPC ≠ 0). A failed CLIENT span with no span from its callee is counted as an **unseen callee**: the callee crashed or isn't instrumented, so the graph can't name it. 4. Failing path = failing services and all their callers. The entry point is the most common root service of the failed traces. 5. Stage 2: keep an anomaly only if its service is on the failing path, and prune the rest with a reason. When M1 can't locate the fault it prunes less: no failing spans → nothing is pruned; an unseen callee → anomalies from services outside the graph are kept. 6. *(Not built yet)* If traces are too sparse, fall back to a static topology (`topology.json`) and set `fallback_used`. 7. Annotate nodes with k8s state: a Pod that isn't Running if there is one, otherwise the first Pod or other object; replicas come from the Deployment. 8. Return plain JSON-friendly models |
| Output | `SemanticContext` (contract model): `kept_signals`, `symptoms` (failed root operations), `nodes`, `dependencies` (failing-path edges, caller → callee), `failing_services`, `entry_point`, `fallback_used`, `strategy`. The Stage 1 set, pruned signals with reasons, and the graph stay in the M1-internal `ContextReport` (`build_report`) for experiments and the UI, not in the contract |
| Dependencies | F1; contract v1. No graph library: the graphs are small and plain sets and dicts are enough. `networkx` was approved on 11 Oct and can be added later if a strategy needs graph algorithms |
| Test evidence | `tests/unit/context/test_sdg.py`, `test_isolator.py` and `test_service.py`. Happy path: CART_ADDR keeps the cart and frontend signals and prunes the product-catalog memory spike and the kube-system noise. Failure paths: cyclic calls, empty input, an empty anomaly set, spans outside the alert window, mixed time zones, no failing spans, an unseen callee, and an unknown strategy. Planned: sparse traces → fallback. Experiment: `experiments/2026-10-18_m1_stage2_failing_path/` |

## Context strategies
`build_context` takes a `strategy`, so one evaluation harness can compare context strategies.
- **Before PP1:** `raw`, `stage1`, `failing_path`.
- **After PP1:** `top_k`, `one_hop`, `time_window` and `failing_path_k8s`.

## Objective → function → metric → evidence

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Give the diagnoser a small context that still contains the fault | Prune Stage 1 anomalies that are off the failing call path, and describe the topology | Context recall (fault entities in the context / fault entities in ground truth), at service and evidence level; NRR; false-prune rate; T_synth (median, compute time reported separately from fetch time), each with *n* | `experiments/2026-10-18_m1_stage2_failing_path/` (n = 1, synthetic): NRR 0.762, labelled NRR 1.0, false-prune rate 0 | `raw` and `stage1` strategies on the same scenarios | PP1: synthetic scenarios, *n* stated. After PP1: SREGym-Lite drills and RCAEval RE2 |
