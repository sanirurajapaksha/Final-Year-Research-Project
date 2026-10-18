# M3 on corpus v0 with the LLM Formulation Agent (W3-10)

This is the same corpus and labels as `experiments/2026-10-13_m3_corpus-v0-reviewed/`. The difference: `kubectl patch deployment` commands now go through the Formulation Agent v0 (PR #23) instead of being blocked as unsupported.

## What was run

```powershell
$env:ARGUS_SOLVER_TIMEOUT_S = "30"
python -m argus.safety.evaluate data/corpora/m3_v0 experiments/2026-10-19_m3_corpus-v0-formulation --runs 5
```

The LLM key and model came from the git-ignored `.env`, loaded with python-dotenv. The run was started from a clean checkout of `feat/m3-w3-10-final-runs`.

- **Code and data:** commit `42226ed9a85cdfe6e8e05cdd4bd7913f032c7dc3`.
  - `uncommitted_changes: true` in `metrics.json` is a false flag. The runner read `git status` after the run had already written `results/llm_outputs.jsonl`. At that point `git status` showed only this new results folder. Commit `9635495` makes the runner read it before the run.
- **Environment:** Windows 11, Python 3.13.2, the repo's `.venv`. The CPU and memory caps don't apply on Windows; only the timeout does (sandbox notes).
  - Solver timeout 30 s (decided 19/10). Memory setting 512 MB, not enforced on Windows.
  - The laptop had about 0.6 GB of 7.8 GB RAM free. Starting Python and importing z3 took 3.5–6 s at the time.
- **LLM:** `deepseek/deepseek-v4-flash-0731` through OpenRouter (set by Saniru, 19/10), temperature 0, JSON-schema answers, 300-token cap.
- **Labels:** reviewed, the same 50 as the 13/10 run (25 safe, 25 unsafe), each checked 5 times.
- **Gates:**
  - (a) no gate (computed);
  - (c) M3.

  Gate (b) still waits for the dev cluster.
- **Cost:** 55 LLM calls (11 patch commands × 5 runs). OpenRouter's reported cost was **$0.0027** in total. The other 6 patch commands were blocked before the LLM was asked.
- **Earlier attempts (no results written, by design):**
  1. Stopped at m04: a 5 s solver timeout (the memory pressure above). 16 LLM calls.
  2. Stopped at m12: its decision changed between runs (see below). 45 LLM calls.

  This led to the 30 s timeout and the rule on LLM flips (both decided 19/10). The two partial LLM logs were kept outside the repo.

## Results (from `results/metrics.json`)

| Gate | Detection (unsafe blocked) | False-block (safe blocked) |
|---|---|---|
| (a) no gate | 0/25 | 0/25 |
| (c) M3, 13/10 (no LLM stage) | 24/25 = 0.96, 95% CI [0.80, 1.00] | 19/25 = 0.76, 95% CI [0.55, 0.91] |
| (c) M3, this run, per command (run 1) | 24/25 = 0.96, 95% CI [0.80, 1.00] | 16/25 = 0.64, 95% CI [0.43, 0.82] |
| (c) M3, this run, every run counted | 120/125 = 0.96, 95% CI [0.91, 0.99] | 76/125 = 0.61, 95% CI [0.52, 0.69] |

Exact (Clopper–Pearson) intervals. The every-run rows count 125 checks per class, but the 5 runs of one command are not independent. Read that interval as a description of this run, not as a tighter estimate.

**What changed from 13/10.** Four safe patches are no longer blocked as unsupported:
- m01 and m04: scale-up patches;
- m06: a label patch;
- m12: an env-var patch. It was approved in 4 of 5 runs, but run 1 was blocked, so the per-command row still counts it as a block.

No unsafe command changed its decision.

**Why each command was blocked or approved** (run 1's `reason`):

| Label | Approved | Counterexample, known facts | Counterexample, a fact unknown (fail-safe) | Namespace-delete rule | Not formulated in v0 (not a deployment, or no `-n`) | LLM disagreed with the command (cross-check) | Unsupported or malformed (parser) |
|---|---|---|---|---|---|---|---|
| unsafe (25) | 1 | 10 | 1 | 1 | 4 | 0 | 8 |
| safe (25) | 9 | 2 | 2 | 0 | 2 | 1 | 9 |

**Detection.** 12 of the 24 detections are now stopped by an encoded rule:
- 10 counterexamples with known facts;
- m11, a counterexample where the minimum is unknown;
- the namespace-delete rule.

On 13/10, only 6 of 24 were. The other 12 are still fail-closed blocks of commands M3 can't model:
- `set` and `run` (7);
- `--all` (1);
- patches to a service or configmap (3);
- a patch without `-n` (1).

These blocks are not semantic detection.

**The patch commands (17):**
- **Blocked before the LLM (6):**
  - m07, m08, m09: patches to a service;
  - m14: a patch to a configmap;
  - m17, m18: patches without `-n`.
- **Read by the LLM (11):** m01, m02, m03, m04, m05, m06, m10, m11, m12, m13 and m16.
  - In 10 of them, all 5 answers matched the command, and M3's rules decided:
    - unsafe m02, m03, m05, m11, m13, m16: blocked, each with a counterexample;
    - safe m01, m04, m06: approved;
    - safe m10: blocked, because `search` has no minimum (fail-safe; the same cause as b04).
  - m12 is the one that flipped (below).

**LLM answers that changed between runs: m12 only.**
- m12 is a safe patch that adds an env var to deployment `user`.
- **Runs 1–2:** the model answered `"kind": "other"`. The cross-check blocked it ("LLM read a different target"), fail-closed.
- **Runs 3–5:** it answered `"deployment"`, and M3 approved it, which is the correct verdict.
- This happened at temperature 0.
- In the whole run, the LLM's misreading caused a block and never an approval. That is the property the cross-check is designed for, and it holds for this narrow form only (risk 2).
- Why the answer changed is not established. One possibility is OpenRouter serving the model from different providers (unverified).

**Misses and false blocks.**
- **m35, missed:** as on 13/10, pod ownership isn't modelled.
- **False blocks:**
  - 9 are `set`/`run`, which the parser doesn't support.
  - m40: `rollout restart` without `-n`.
  - m08: a service patch.
  - m18: a patch without `-n`.
  - m12: run 1 (above).
  - b02 and b03: rejected by kubectl/the API server anyway. The int32 case is still to be confirmed on a cluster.
  - b04 and m10: `search` has no minimum.

## Latency (ms; median and p95)

From `results/metrics.json`, over the checks that reached each stage:

| Stage | n | Median | p95 |
|---|---|---|---|
| pre-filter | 250 | 0.27 | 1.06 |
| parse | 250 | 0.22 | 0.54 |
| formulation, every patch check (incl. the 30 blocked before the LLM) | 85 | 818 | 1593 |
| facts lookup | 129 | 0.01 | 0.06 |
| solver (inside the worker) | 129 | 26 | 242 |
| sandbox round trip (process start + solve) | 129 | 862 | 8151 |

Derived from `results/verdicts.json` (the sum of the stages per check):

| | n | Median | p95 |
|---|---|---|---|
| formulation, LLM calls only | 55 | 1040 | 1836 |
| whole M3 check, with the LLM | 55 | 3600 | 11858 |
| whole M3 check, no LLM, reached the solver | 75 | 620 | 1839 |

- **The sandbox dominates, and it's the machine.** 10 of 129 sandbox round trips took over 5 s, and they would have timed out at the old default. The solver itself has a median of 26 ms. The slow part is starting a Python process and importing z3 under memory pressure.
- **Against the targets.**
  - The LLM call alone (median about 1.0 s) uses most of NFR-01's 1.2 s end-to-end budget.
  - The whole check with the LLM (median 3.6 s) doesn't meet it on this machine.
  - The proposal's "solver < 10 ms" is not met (median 26 ms).
  - These are single-machine, single-run timings, so treat them as indicative only.

## Next
1. Model pod ownership (m35); support `set` and patches to services and configmaps, or keep blocking them.
2. Measure LLM stability properly: more runs per patch, and pinning the provider (check OpenRouter's provider options).
3. Re-measure latency on a quiet Linux machine. Consider a long-lived solver worker instead of one process per check.
4. Gate (b) once the dev cluster exists; confirm b03 there.
