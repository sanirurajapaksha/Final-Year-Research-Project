# M3: Proactive Formal Verification Safety Layer

**Owner:** Saniru Rajapaksha

**Role in the flow:** every write command goes M2 → M4 → **M3** before it runs. APPROVE → M4's execution handler. BLOCK → the counterexample goes back to M2.

**Entry point:** `gate.check(ProposedAction, snapshot=None, settings=None) -> SafetyVerdict`. Without a snapshot (until the live extractor exists) every write is blocked (fail-closed).

**Status (F1 slice, W1-08 + W2-02 + W2-04):** on a fixture snapshot, M3 checks
- `kubectl scale deployment` against minimum replicas (I1) and protected namespaces (I2);
- `kubectl delete` of a pod, PVC or namespace against protected namespaces (I2) and in-use PVCs (I4);
- `kubectl rollout restart deployment` against minimum availability during the restart (I3) and protected namespaces (I2).

Deleting a namespace that isn't protected is blocked (fail-closed). Every other command is blocked. The protected namespaces are M3's own list in `policy.py`. Spec: `docs/functions/m3-F1-offline-gate.md`.

```bash
python -m argus.safety "kubectl scale deployment geo --replicas=1 -n hotel-reservation" --snapshot data/fixtures/m3/snapshot_hotel_reservation.json
```

| Step | File | What it does | Status |
|---|---|---|---|
| 0 | `prefilter.py` | Syntactic checks (single kubectl command; no pipes, compound commands, substitution, `$` or `#`, redirects, interactive or stdin forms; no `exec`/`edit`/…). No LLM. | done |
| 1 | `snapshot.py` | Looks up the target's facts in a snapshot (the format the extractor will produce). | done (fixture) |
| — | `policy.py` | M3's own policy values: the protected namespaces. | done |
| 1 | `extractor.py` | Read-only cluster queries → snapshot. No LLM. | F2 |
| 2a | `parser.py` | Command → structured action (deterministic templates). | `scale`, `delete`, `rollout restart` |
| 2a | `formulation.py` | LLM → typed JSON action for commands the parser doesn't support. | F2 |
| 2b | `compiler.py` | Action + facts → Z3 constraints; solves them. Hand-written encodings, no generated code. | I1, I2, I3, I4 |
| 3 | `worker.py`, `sandbox.py` | Runs the compiler in a subprocess with a timeout (and CPU/memory caps on Linux). | done |
| — | `gate.py` | Wires the steps; maps the raw result to APPROVE/BLOCK; records per-stage timings. | done |
| — | `evaluate.py` | Runs a labelled corpus through the gate: detection and false-block rates with exact 95% CIs, latency per stage (`python -m argus.safety.evaluate CORPUS OUT --runs 5`; needs the `eval` extra). | done (corpus v0) |

**Rules**
- Keep Z3's raw result (`sat` / `unsat` / `unknown`) separate from the gate decision (APPROVE / BLOCK).
- On the negated safety property: `unsat` → APPROVE; `sat` → BLOCK with the counterexample; `unknown`, timeout or error → BLOCK.
- Never `exec` or `eval` LLM output. The solver runs only in the sandboxed worker, which reads data and runs no generated code.
- The extractor uses read-only verbs only: get, list, watch.
- Every invariant needs tests with at least one safe and one unsafe case, plus edge cases: 0 or negative replicas, integer overflow, missing resources.
- Time each stage separately (`common.timing.stage_timer`) and keep raw result files.
- The memory cap needs Linux: develop and measure M3 in WSL or rely on CI.

**Sandbox settings** (environment variables, see `.env.example`):
- `ARGUS_SOLVER_TIMEOUT_S` (default 5): wall-clock limit per check.
- `ARGUS_SOLVER_MEMORY_MB` (default 512): address-space cap for the worker (Linux only).

If every check is blocked with `worker exited with code 1: MemoryError`, the cap is too small for that machine; raise it. 256 MB was too small on Fedora.

Tests go in `tests/unit/safety/`.
