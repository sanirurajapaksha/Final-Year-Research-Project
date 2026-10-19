# M1 Stage 2: failing-path pruning against Stage 1 alone

Date: 2026-10-18
Task: W3-04
Owner: Minidu Weerasinghe

## What was run
`python experiments/2026-10-18_m1_stage2_failing_path/run.py` from the repository root, on commit `895b830` with no other uncommitted changes (see `config.json`).

- **Data:** `data/fixtures/m1/scenario_01/telemetry.json`. This is the same hand-written, **synthetic** CART_ADDR scenario as the Stage 1 run (`2026-10-11_m1_stage1_nrr`). It has 27 records, 6 of them spans. **n = 1.**
- **Labels:** `ground_truth.json`, `stage1_expected.relevant`. There are 5 evidence signals; every other Stage 1 input signal counts as noise.
- **Denominator:** the 21 metric, log and k8s records, as in the Stage 1 run. Spans build the graph and aren't counted as candidate signals.
- **Strategies:** both go through M4's real `compress()` and M1's `build_report()`.
  - `stage1` is the F1 threshold filter.
  - `failing_path` adds the service dependency graph and Stage 2 pruning.
- **Settings:**
  - Default thresholds.
  - A 5-minute lookback before `alert_time`. All 6 spans fall inside it.
- No model was called and no cluster command was run.

## Results (`results/summary.json`)

| Strategy | Kept | Evidence kept | Noise kept | NRR | Labelled NRR | False-prune rate | Fault service in context |
|---|---|---|---|---|---|---|---|
| `stage1` | 8 | 5 / 5 | 3 | 0.619 | 0.813 | 0.0 | yes |
| `failing_path` | 5 | 5 / 5 | 0 | **0.762** | **1.0** | **0.0** | yes |

- **Graph:**
  - Edges are frontend → cart and frontend → product-catalog.
  - Failing services are cart and frontend. The entry point is frontend.
  - The context's `dependencies` keep only frontend → cart.
- **Pruned by Stage 2** (reasons from the M1-internal report):
  - The product-catalog memory spike: "in the call graph but not on the failing path".
  - metrics-server's error log and restarts: "not in the call graph".
- The context gets 2 services instead of 4.
- `results/context_failing_path.json` is the exact `SemanticContext` M2 would receive.
- **Compute time:** median 0.36 ms over 200 runs. Window, graph and pruning together take about 0.03 ms. Input is in memory, so there is no fetch time.

## What this shows, and what it doesn't
- On this scenario, Stage 2 removes all the noise that Stage 1 lets through and keeps every evidence signal.
- **NRR is 0.762, below the proposal's PP1 target of 0.80, even though labelled NRR is 1.0.** The 5 kept signals are all evidence. The simple NRR can't go higher without dropping evidence, because the scenario only has 21 candidate signals. Report both ratios.
- **n = 1, synthetic, and written by the same person as the code.** The scenario was designed with exactly this distraction, so the result shows the mechanism works. It doesn't show how often it works.
- **Known gaps, still to build or test:**
  - **Sparse traces:** with no failing spans, Stage 2 prunes nothing. The static-topology fallback (`fallback_used`) isn't built yet.
  - **Uninstrumented callees:** a crashed root cause such as Redis emits no span. When a failed call has no callee span, Stage 2 keeps signals from services outside the graph rather than risk pruning the fault. No scenario tests this yet.
  - **Faults without error spans:** a fault that shows up only as latency or a pod crash, with no error span, isn't located. Nothing is pruned in that case.
- **Next:**
  - More scenarios, so that n > 1: an uninstrumented-callee fault and a sparse-trace fault.
  - The `raw` strategy as a baseline.
  - The static-topology fallback.
