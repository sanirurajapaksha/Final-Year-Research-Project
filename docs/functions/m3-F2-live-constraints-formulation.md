# Function spec: M3 F2 — live constraints and LLM formulation

Status: spec only (planned for Week 3).

| Field | |
|---|---|
| Name | Live constraints and LLM formulation (M3 Function 2) |
| Owner | Saniru Rajapaksha |
| Input | The same write command as F1, plus read-only access to the dev cluster. Test data: the kind dev cluster with a small sample app; recorded snapshots as a fallback. |
| Processing logic | 1. **Constraint Extractor:** read-only queries (get, list, watch) around the target object build the snapshot in F1's format, using a Kubernetes account that can only read. 2. Commands the F1 parser supports go straight to F1. 3. Others go to the **Formulation Agent:** an LLM produces a typed, schema-validated JSON description of the command (verb, target, effect, parameters); it is data, never executed. 4. The same sandboxed worker solves it. |
| Output | The same `SafetyVerdict`, plus extraction and formulation timings, and the raw LLM output kept as evidence. |
| Dependencies | F1; the dev cluster (W2-11); a shared read-only cluster client in `src/argus/integrations/`; an LLM provider (plan decision D2); contract v1. |
| Test evidence | Extractor tests against the dev cluster; translation accuracy on a small hand-checked set (parses, runs, matches dry-run or observed state, verdict matches the label); failure paths (cluster unreachable, LLM timeout or invalid JSON) end in BLOCK. |

## Open points
- Direct reads vs reads through M4 (RESEARCH_CONTEXT §5): proposed direct, read-only; needs team agreement and a check of SREGym's rules.
- The snapshot can change between the check and the write: record the snapshot time (or `resourceVersion`) and list it as a limitation.
- Model tier: develop on a cheap model; evaluate on a stronger one (NSVIF got worse with a small model).

## Objective → function → metric → evidence

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Check commands against live cluster state (FR-02, FR-03) | Extractor + Formulation Agent | Extraction latency; translation accuracy on a hand-checked set | Extractor tests; formulation results under `experiments/` | F1 template path; gate (b) | One non-template verb class (e.g. `patch`) for PP1 |
