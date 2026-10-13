# M1 Stage 1: first noise-reduction ratio

Date: 2026-10-11
Task: W2-06
Owner: Minidu Weerasinghe

## What was run
`python experiments/2026-10-11_m1_stage1_nrr/run.py` from the repository root, on commit `ffdab8d` with no other uncommitted changes (see `config.json`).

**Re-run on 2026-10-13:** the first run (11 Oct) recorded commit `79d1a41`, which no longer exists after the branch was rebased onto `main`. The script was run again unchanged on `3053ffb`, so the recorded hash can be checked out.

**Re-run again on 2026-10-13 (evening):** the branch was then rebased onto `main` with GitHub's "Update branch", which dropped `3053ffb` too. The script was run unchanged on the new head `ffdab8d`. Counts and ratios are identical; only the timings changed. The counts and ratios are identical; only the timings differ slightly (machine noise). The results files are the script's output, not edited by hand.

- **Data:** `data/fixtures/m1/scenario_01/telemetry.json`. One hand-written, **synthetic** scenario (Stratus CART_ADDR example), 27 records. **n = 1.** It is not recorded telemetry: the dev cluster isn't up yet.
- **Labels:** `ground_truth.json`, `stage1_expected.relevant`. 5 evidence signals; every other Stage 1 input signal counts as noise.
- **Stage 1 input:** the 21 metric, log and k8s records. The 6 spans are F2 input and are not counted.
- No model was called. No cluster command was run.

## Results (`results/summary.json`)

| Metric | Value | Definition |
|---|---|---|
| NRR | **0.619** | 1 − kept / raw = 1 − 8 / 21 |
| Labelled NRR | **0.813** | Noise removed / labelled noise = 13 / 16 |
| False-prune rate | **0.0** | Evidence removed / labelled evidence = 0 / 5 |
| Compute time, median of 200 | 0.35 ms | Decode 0.25 ms, parse 0.06 ms, filter 0.03 ms. In-memory input, so no fetch time is included |

- The same 8 signals come out whether F1 runs on the records directly or through M4's real `compress()` and `build_context()` (`same_result_via_m4_compress_and_build_context: true`).
- `results/anomalies.json` lists the 8 kept signals.

## What this shows, and what it doesn't
- Stage 1 keeps all the fault evidence and removes most of the noise. The 3 noise signals it keeps (the product-catalog memory spike, and metrics-server's errors and restarts) all cross a threshold. Removing them is Stage 2's job, which needs the service graph (F2, W3-04).
- **One synthetic scenario says nothing about general performance.** The thresholds are first guesses, and the scenario was written together with the filter. Report these numbers with "n = 1, synthetic".
- The PP1 target in the proposal (NRR ≥ 80%) applies to the full pipeline, after Stage 2.
- **Next:** more scenarios (synthetic now, recorded when the cluster is up), and the same metrics after Stage 2.
