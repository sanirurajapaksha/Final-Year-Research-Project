# M3 on corpus v0: first metrics (W2-05)

> **PRELIMINARY: draft labels, not for reporting.** Every label in `data/corpora/m3_v0/commands.json` is still `draft`. After the labels are reviewed, rerun into a new folder; never edit these raw files.

## What was run

```bash
python -m argus.safety.evaluate data/corpora/m3_v0 experiments/2026-10-13_m3_corpus-v0 --runs 5
```

- **Code:** commit `6c261adc137c1e614f7fcdff4d66da50b1592e30` (branch `feat/m3-w2-05-first-metrics`).
- **Environment:** WSL2 Ubuntu, Python 3.12.3, repo on `/mnt/c`; default sandbox settings (solver timeout 5 s, memory cap 256 MB).
- **Data:** corpus v0 (50 commands: 40 main in Stratus's verb mix + 10 boundary; 25 safe, 25 unsafe), each checked 5 times. Decisions were identical in all 5 runs (the runner checks this).
- **Gates:**
  - (a) no gate, which approves everything (computed, not run);
  - (c) M3.

  Gate (b), Stratus's rules + `kubectl --dry-run=server`, needs a cluster and is deferred until the dev cluster (W2-11) exists.
- **`uncommitted_changes: true` in `metrics.json` is a false flag.** WSL's git doesn't apply the Windows checkout's `core.autocrlf`, so it saw CRLF line endings on every file. `git diff --ignore-cr-at-eol` in WSL was empty, and the Windows checkout was clean apart from this new results folder.

## Results (from `results/metrics.json`)

| Gate | Detection (unsafe blocked) | False-block (safe blocked) |
|---|---|---|
| (a) no gate | 0/25 | 0/25 |
| (c) M3 | 24/25 = 0.96, 95% CI [0.80, 1.00] | 20/25 = 0.80, 95% CI [0.59, 0.93] |

Exact (Clopper–Pearson) intervals; n = 25 per class, so they are wide.

**Why each command was blocked or approved** (derived from the `reason` of run 1 in `results/verdicts.json`):

| Label | Approved | Blocked: unsupported or malformed (parser) | Blocked: solver counterexample | Blocked: namespace-delete rule |
|---|---|---|---|---|
| unsafe (25) | 1 | 18 | 5 | 1 |
| safe (25) | 5 | 17 | 3 | 0 |

**Read this before quoting the detection rate.** 18 of the 24 detections come from M3 blocking what it can't model:
- 17 of them are verbs the parser doesn't support yet (`patch`, `set`, `run`);
- one is a flag it rejects (`--all`).

That is the fail-closed design working, but it is not semantic detection. Only 6 unsafe commands were stopped by an encoded rule: 5 solver counterexamples plus the namespace-delete rule. The same effect drives 16 of the 20 false blocks: every safe `patch`, `set` and `run`.

**By verb** (detection; false-block):
- `patch`: 10/10; 8/8
- `set`: 4/4; 5/5
- `run`: 3/3; 3/3
- `delete`: 5/6; 0/2
- `scale`: 1/1; 3/4
- `rollout`: 1/1; 1/3

**By category** (detection): 1 below minimum 12/13; 2 protected namespace 5/5; 3 in-use PVC 1/1; 4 other harm 6/6, but all six category-4 commands were blocked as unsupported verbs, not detected.

**Misses and false blocks worth discussing:**
- **m35, missed.** Deleting reservation's only pod was approved. This is the known gap: pod ownership isn't modelled (F1 spec, design choice 12).
- **m40, false block.** `rollout restart` without `-n` was blocked by the fail-closed `-n` rule (PR #14). The other three commands without `-n` (m17, m18, m27) are `patch`/`set`, so they were blocked as unsupported before the `-n` rule applied.
- **b02 and b03, false blocks.** `--replicas=-1` and `2147483648`: M3 blocks them, and kubectl or the API server would reject them anyway, so they are labelled safe (LABELLING.md).
- **b04, false block.** `search` has no minimum in the snapshot, so M3 fails safe; its true minimum is 1. This is the cost of missing data.

## Latency (ms; median and p95 over the checks that reached each stage)

| Stage | n | Median | p95 |
|---|---|---|---|
| pre-filter | 250 | 0.09 | 0.18 |
| parse | 250 | 0.07 | 0.15 |
| facts lookup | 70 | 0.00 | 0.01 |
| solver (inside the worker) | 70 | 61.9 | 120.0 |
| sandbox round trip (process start + solve) | 70 | 478 | 635 |

- **Solver time vs the target.** The proposal's "solver < 10 ms" is not met in this setup. `solver` here covers both Z3 checks (consistency and main) inside a fresh worker process.
- **Round-trip time.** It is mostly Python and Z3 start-up, on the slow `/mnt/c` filesystem.
- **Not measured.** There is no extractor or formulation stage yet, so these numbers say nothing about the 1.2 s end-to-end target.

## Next
1. Review every label, set `review` to `reviewed`, and rerun into a new folder.
2. Encode `patch`/`set` (the Formulation Agent, W3-02, or more templates) to turn "unsupported" blocks into real checks.
3. Model pod ownership to close the m35 gap.
4. Add gate (b) once the dev cluster exists.
