# Contracts between modules (draft v0)

The typed messages in `src/argus/contracts/` are a first draft for **contract v1**, which all four owners agree together (Planner task W2-01). Until then, change them freely, but in a PR that every affected owner sees.

| Model | From → to | File |
|---|---|---|
| `TelemetryBatch` | benchmark → M4 | `telemetry.py` |
| `CompressedTelemetry` | M4 → M1 | `telemetry.py` |
| `SemanticContext` | M1 → M4 → M2 | `context.py` |
| `DiagnosisResult`, `Hypothesis`, `ProposedAction` | M2 → M4 (→ M3 for writes) | `diagnosis.py` |
| `SafetyVerdict`, `Z3Result`, `GateDecision` | M3 → M4; M3 → M2 on BLOCK | `safety.py` |
| `ExecutionResult` | M4's execution handler | `execution.py` |

## Rules
1. **Commands are byte-exact.** `ProposedAction.command` is never compressed, trimmed or rewritten after M2 creates it. M3 checks exactly the string that will run.
2. **M3's raw solver result and its decision are separate fields.** `z3_result` is Z3's answer on the negated safety formula; `decision` is APPROVE or BLOCK.
   - `unsat` → APPROVE
   - `sat` → BLOCK, with the counterexample
   - `unknown`, timeout or error → BLOCK
3. **Naming.** Reports describe M3's verdicts as SAT (safe) and UNSAT (unsafe). The code never uses those words for the decision, so the safe verdict can't be confused with Z3's raw `sat`.
4. **Counterexamples go back to M2** through `diagnose(..., feedback=[...])`.
5. **Changing a contract:** open a PR that touches `contracts/` and get approval from every owner whose module sends or receives that model.
