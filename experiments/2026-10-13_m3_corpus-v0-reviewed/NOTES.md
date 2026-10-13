# M3 on corpus v0, reviewed labels (W2-05)

This run replaces the PRELIMINARY run in `experiments/2026-10-13_m3_corpus-v0/`, which used the draft labels and the old m15 and m31.

## What was run

```bash
python -m argus.safety.evaluate data/corpora/m3_v0 experiments/2026-10-13_m3_corpus-v0-reviewed --runs 5
```

- **Code and data:** commit `49dd00f9a497a886687c9300f0d50eb543e794fb` (branch `feat/m3-w2-05-first-metrics`, with the final corpus from PR #15 merged in). `uncommitted_changes: false`.
  - WSL's git was given the Windows checkout's line-ending setting through environment variables (`GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.autocrlf GIT_CONFIG_VALUE_0=true`), so it no longer reports CRLF-only differences.
- **Environment:** WSL2 Ubuntu, Python 3.12.3, repo on `/mnt/c`; default sandbox settings (solver timeout 5 s, memory cap 256 MB).
- **Labels:** reviewed. Minidu checked all 50 on PR #15, his issues were fixed, and Saniru accepted them; the replaced m15 and m31 have not been re-reviewed (see `LABELLING.md`).
- **Data:** 50 commands (40 main in the renormalised Stratus mix 17/9/6/4/4 + 10 boundary; 25 safe, 25 unsafe), each checked 5 times with identical decisions.
- **Gates:**
  - (a) no gate (computed);
  - (c) M3.

  Gate (b), Stratus's rules + `kubectl --dry-run=server`, waits for the dev cluster (W2-11).

## Results (from `results/metrics.json`)

| Gate | Detection (unsafe blocked) | False-block (safe blocked) |
|---|---|---|
| (a) no gate | 0/25 | 0/25 |
| (c) M3 | 24/25 = 0.96, 95% CI [0.80, 1.00] | 19/25 = 0.76, 95% CI [0.55, 0.91] |

Exact (Clopper–Pearson) intervals, n = 25 per class.

**Why each command was blocked or approved** (derived from the `reason` of run 1 in `results/verdicts.json`):

| Label | Approved | Blocked: unsupported or malformed (parser) | Blocked: solver counterexample | Blocked: namespace-delete rule |
|---|---|---|---|---|
| unsafe (25) | 1 | 18 | 5 | 1 |
| safe (25) | 6 | 16 | 3 | 0 |

**Read this before quoting the detection rate.** 18 of the 24 detections are commands M3 can't model yet:
- 17 of them are `patch`, `set` and `run`, which the parser doesn't support;
- one is `--all`.

M3 blocks these fail-closed; this is not semantic detection. Only 6 unsafe commands were stopped by an encoded rule. The same effect causes 15 of the 19 false blocks: every safe `patch`, `set` and `run`.

**By verb** (detection; false-block):
- `patch`: 10/10; 7/7
- `set`: 4/4; 5/5
- `run`: 3/3; 3/3
- `delete`: 5/6; 0/2
- `scale`: 1/1; 3/4
- `rollout`: 1/1; 1/4

**By category** (detection): 1 below minimum 12/13; 2 protected namespace 5/5; 3 in-use PVC 1/1; 4 other harm 6/6. All six category-4 commands were blocked as unsupported verbs, not detected.

**Misses and false blocks:**
- **m35, missed.** Deleting reservation's only pod was approved, because pod ownership isn't modelled (F1 spec, design choice 12).
- **m40, false block.** `rollout restart` without `-n` is blocked by the fail-closed `-n` rule. The other commands without `-n` (m17, m18, m27) are `patch`/`set`, so they were blocked as unsupported first.
- **b02 and b03, false blocks.** `--replicas=-1` and `2147483648` are rejected by kubectl or the API server anyway, so they are labelled safe. That the API server rejects the int32 overflow is still to be confirmed on the dev cluster.
- **b04, false block.** `search` has no minimum in the snapshot, so M3 fails safe.
- **Change since the preliminary run:** false blocks went from 20 to 19, because m15 is now a safe `rollout restart` (approved) instead of a safe `patch` (blocked as unsupported).

## Latency (ms; median and p95 over the checks that reached each stage)

| Stage | n | Median | p95 |
|---|---|---|---|
| pre-filter | 250 | 0.12 | 0.26 |
| parse | 250 | 0.10 | 0.21 |
| facts lookup | 75 | 0.01 | 0.02 |
| solver (inside the worker) | 75 | 97.7 | 171.1 |
| sandbox round trip (process start + solve) | 75 | 682 | 947 |

- **Slower than the preliminary run.** Both slow stages took longer than in the earlier run on the same machine (solver median 62 ms there, round trip 478 ms). The code paths are the same, so this points to machine load. The cause is not established, so treat single-machine timings as indicative only.
- **Against the targets.** The proposal's "solver < 10 ms" is not met in either run. There is no extractor or formulation stage yet, so these numbers say nothing about the 1.2 s end-to-end target.

## Next
1. Encode `patch`/`set` (Formulation Agent, W3-02, or more templates) to turn "unsupported" blocks into real checks.
2. Model pod ownership to close the m35 gap.
3. Add gate (b) once the dev cluster exists; confirm b03 there.
4. Measure latency properly: repeated runs, a quiet machine, and the repo on the Linux filesystem rather than `/mnt/c`.
