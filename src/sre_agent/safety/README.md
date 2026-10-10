# M3: Proactive Formal Verification Safety Layer

**Owner:** Saniru Rajapaksha

**Role in the flow:** every write command goes M2 → M4 → **M3** before it runs. APPROVE → M4's execution handler. BLOCK → the counterexample goes back to M2.

**Entry point:** `gate.check(ProposedAction) -> SafetyVerdict`. For now only the pre-filter step exists, and every write is blocked (fail-closed).

| Step | File | What it does |
|---|---|---|
| 0 | `prefilter.py` | Syntactic checks (pipes, compound commands, interactive forms). No LLM. |
| 1 | `extractor.py` | Read-only cluster queries → invariants and current state. No LLM. |
| 2a | `formulation.py` | Command → typed intermediate representation (templates first, LLM for the long tail). |
| 2b | `compiler.py` | Representation + invariants → Z3 script. |
| 3 | `sandbox.py` | Runs the script in a subprocess with a timeout and a memory cap. |

**Rules**
- Keep Z3's raw result (`sat` / `unsat` / `unknown`) separate from the gate decision (APPROVE / BLOCK).
- On the negated safety formula: `unsat` → APPROVE; `sat` → BLOCK with the counterexample; `unknown`, timeout or error → BLOCK.
- Never `exec` or `eval` LLM output in-process. Generated scripts run only in the sandbox.
- The extractor uses read-only verbs only: get, list, watch.
- Every invariant needs tests with at least one safe and one unsafe case, plus edge cases: 0 or negative replicas, integer overflow, missing resources.
- Time each stage separately (`common.timing.stage_timer`) and keep raw result files.

Tests go in `tests/unit/safety/`.
