# Function spec: M3 F1 — offline safety gate

| Field | |
|---|---|
| Name | Offline safety gate (M3 Function 1) |
| Owner | Saniru Rajapaksha |
| Input | One write command, byte-exact as M2 proposed it (`ProposedAction`), and a cluster snapshot (JSON). Test data: hand-written fixture `data/fixtures/m3/snapshot_hotel_reservation.json`. |
| Processing logic | 0. Pre-filter rejects shapes M3 can't reason about. 1. Parser turns the command into a structured action (F1: `kubectl scale deployment`). 2. The target's facts are looked up in the snapshot. 3. A sandboxed worker builds the Z3 constraints for the minimum-replicas invariants and solves them. 4. The raw result is mapped to APPROVE / BLOCK. |
| Output | `SafetyVerdict` (contract in `src/argus/contracts/safety.py`): raw `z3_result`, `decision`, `reason`, `violated_invariants`, `counterexample`, `timings_ms` per stage. Any early stop or error → BLOCK with the stage named in `reason`. |
| Dependencies | `z3-solver`; contracts `ProposedAction`, `SafetyVerdict`; `Settings.solver_timeout_s`, `Settings.solver_memory_mb`. No cluster, no LLM. |
| Test evidence | `tests/unit/safety/`: `test_prefilter.py`, `test_parser.py`, `test_compiler.py` (safe, unsafe, 0, negative, int32 overflow, missing facts, already-broken cluster, malformed facts), `test_sandbox.py` (round trip, timeout, worker error, memory cap on Linux), `test_gate.py` (end to end). CI runs them on Linux. |

Try it:

```bash
python -m argus.safety "kubectl scale deployment geo --replicas=1 -n hotel-reservation" --snapshot data/fixtures/m3/snapshot_hotel_reservation.json
```

## The check

Variables: $r_0$ replicas before, $r_1$ replicas after, $m$ minimum replicas (policy), target $k$ from `--replicas=k`.

$$\mathit{Facts}(S_0) \equiv 0 \le r_0, m \le 2^{31}-1 \;\land\; r_0 = \hat r_0 \;\land\; m = \hat m \quad (\text{only for facts present in the snapshot})$$
$$T(S_0, A, S_1) \equiv r_1 = k$$
$$I(S) \equiv \underbrace{0 \le r_S \le 2^{31}-1}_{\texttt{replicas\_in\_int32\_range}} \;\land\; \underbrace{r_S \ge m}_{\texttt{min\_replicas}}$$

Z3 is asked whether $\mathit{Facts}(S_0) \land T(S_0, A, S_1) \land \lnot I(S_1)$ is satisfiable.

*In plain language:* "given what we know about the cluster, and what `scale` does, is there any end state where the deployment has fewer than its minimum replicas or an impossible replica count?" If yes (`sat`), Z3's example is the counterexample and the command is blocked. If no (`unsat`), the command is approved, **with respect to these two invariants only**.

| Raw Z3 result | Decision | Report label |
|---|---|---|
| `unsat` | APPROVE | SAT (safe) |
| `sat` | BLOCK + counterexample | UNSAT (unsafe) |
| `unknown`, timeout, error, no result | BLOCK | — |

The code stores the raw result and the decision only; the SAT/UNSAT report labels are derived from them, never stored (team naming rule).

## Design choices (to defend, some still to confirm)

1. **Fail-closed** for `unknown`, timeouts and errors (plan decision D4). Applied in code; Saniru to confirm.
2. **$I(S_0)$ is not assumed.** The proposal's formula is $I(S_0) \land T \land \lnot I(S_1)$. During an incident the cluster often already breaks an invariant (e.g. `rate` has 0 of its 2 minimum replicas). Then $I(S_0)$ is false, the whole formula is unsatisfiable, and *every* command would be approved (vacuous truth). Dropping $I(S_0)$ only removes a premise, so the gate can block more commands, never fewer. Invariants already broken before the command are reported in `reason`. **Deviation from the proposal: Saniru to decide.**
3. **Consistency check first.** If the snapshot facts and the transition contradict each other, the main check would also be vacuously `unsat`. So that case is an error (BLOCK), never an APPROVE.
4. **Missing facts stay unconstrained.** If the snapshot lacks a value, Z3 may choose any valid value for it, including one that breaks an invariant. Missing data therefore fails safe through the formula itself (e.g. `search` has no `min_replicas`, so scaling it is blocked), and `reason` lists the missing facts.
5. **Z3 integers are unbounded**, Kubernetes replica counts are int32. The range is therefore an explicit invariant (overflow edge case).
6. **Fixed worker, not generated code.** The compiler is a hand-written module run in a subprocess; it reads JSON and never executes generated code. The proposal's FR-04 says "compile to a Python Z3 script"; this would become "compile to Z3 constraints solved in a sandboxed worker". **Saniru to decide.**
7. **Sandbox limits:** wall-clock timeout everywhere; CPU-time and memory caps on Linux only (the `resource` module doesn't exist on Windows). Z3's own timeout is 80% of the process timeout.
8. **Parser scope:** `kubectl scale deployment` only, unknown flags rejected (not ignored), missing `-n` means `default`. Negative counts parse on purpose, so the encoding (not the parser) is what blocks them.
9. **Where `min_replicas` comes from on a live cluster** (PodDisruptionBudget, annotation or project config) is open; F1 reads it from the fixture.

## Observations so far (informal, not evidence)

One manual run each on WSL (files on `/mnt/c`): solver step about 60–100 ms, subprocess round trip about 0.5–0.6 s, mostly Python and Z3 start-up. Both are well above the proposal's "solver < 10 ms" target. Measure properly (median and p95, with n) before reporting; options if confirmed: a long-lived worker process, or in-process solving.

## Objective → function → metric → evidence

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Block unsafe state-changing commands before they run (proposal Obj. 2, FR-01–FR-06) | Offline gate on fixture snapshots | Detection rate and false-block rate with exact 95% CIs; latency per stage | `tests/unit/safety/`; corpus v0 results under `experiments/` (W2-03, W2-05) | (a) no gate; (b) Stratus's rules + `kubectl --dry-run=server` | Synthetic corpus v0 for PP1 (verb mix from SREGym Table 11); real Stratus commands after the baseline runs (AP-03) |
