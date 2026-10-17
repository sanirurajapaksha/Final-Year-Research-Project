# Function spec: M3 F2 — live constraints and LLM formulation

Status: Constraint Extractor built on saved kubectl output (W3-01); Formulation Agent v0 built for `kubectl patch deployment` (W3-02).

| Field | |
|---|---|
| Name | Live constraints and LLM formulation (M3 Function 2) |
| Owner | Saniru Rajapaksha |
| Input | The same write command as F1, plus read-only access to the dev cluster. Test data: the kind dev cluster with a small sample app; recorded snapshots as a fallback. |
| Processing logic | 1. **Constraint Extractor:** read-only queries (get, list, watch) around the target object build the snapshot in F1's format, using a Kubernetes account that can only read. 2. Commands the F1 parser supports go straight to F1. 3. Others go to the **Formulation Agent:** an LLM produces a typed, schema-validated JSON description of the command (verb, target, effect, parameters); it is data, never executed. 4. The same sandboxed worker solves it. |
| Output | The same `SafetyVerdict`, plus extraction and formulation timings, and the raw LLM output kept as evidence. |
| Dependencies | F1; the dev cluster (W2-11); a shared read-only cluster client in `src/argus/integrations/`; an LLM provider (plan decision D2); contract v1. |
| Test evidence | Extractor tests against the dev cluster; translation accuracy on a small hand-checked set (parses, runs, matches dry-run or observed state, verdict matches the label); failure paths (cluster unreachable, LLM timeout or invalid JSON) end in BLOCK. |

## Constraint Extractor (built in W3-01, on saved kubectl output)

The dev cluster is deferred past PP1, so the extractor runs on saved kubectl output for now. The code is the same as for a live cluster.

- **What it reads.** `extractor.extract(namespace, run)` sends four read-only commands: `kubectl get deployments|pdb|pods|pvc -n NS -o json`. From them it builds the snapshot in F1's format.
- **Where it reads from.** Every command goes through a `run(command)` function, chosen by the settings:
  - `ARGUS_M3_KUBECTL_OUTPUT`: a folder of saved output, the PP1 setting (`data/fixtures/m3/kubectl/`);
  - `ARGUS_KUBE_CONTEXT`: live kubectl, always run with that `--context`;
  - later, SREGym's Kubernetes MCP server, which wraps the kubectl CLI (SREGym CAIS '26, §2.2), so it can take the same commands. Its exact tool interface is unverified until we have a cluster.
- **Read-only.** The extractor only builds `kubectl get` commands, and both runners refuse anything else.
- **Where each fact comes from:**

| Fact | Source |
|---|---|
| `replicas` | `spec.replicas` |
| `max_unavailable`, `max_surge` | `spec.strategy.rollingUpdate`. The `Recreate` strategy counts as `100%` / `0`. |
| `min_replicas` | The one PodDisruptionBudget whose selector picks the deployment's pods: its `minAvailable`, with a percentage rounded up (Kubernetes docs). No PDB, more than one, a PDB with only `maxUnavailable`, or `matchExpressions` → unknown, so M3 blocks (fail-safe). |
| PVC `in_use` | A pod in the namespace mounts it (`spec.volumes[].persistentVolumeClaim.claimName`). |

- **Gate.** With no snapshot passed in, the gate calls the extractor for the command's namespace and times it as the `extractor` stage. Any extractor error blocks.
- **Check against F1.** On six commands, the extractor-built facts and the hand-written snapshot give the same decisions (`test_gate.py`).

## Formulation Agent v0 (built in W3-02): `kubectl patch deployment`

The fixed parser reads `scale`, `delete` and `rollout restart`. A `kubectl patch` (39% of Stratus's writes, SREGym Table 11) goes to an LLM instead:

```
command text ──► M3 reads name, -n, patch JSON itself (no LLM)
            └──► LLM (OpenRouter, google/gemini-2.5-flash-lite, JSON-schema answer)
                    {kind, name, namespace, effect, replicas}
                 ──► Pydantic validation ──► cross-check with what M3 read ──► an action M3's rules check
```

| LLM says `effect` | M3 checks it as | Rules |
|---|---|---|
| `set_replicas` (only `spec.replicas`) | `scale` | I1, I2 |
| `pod_template_change` (only `spec.template`) | `rollout-restart` (a template change starts a rolling update) | I3, I2 |
| `metadata_only` (only the deployment's own `metadata`) | `patch-metadata` | I2 only (decided 17/10) |
| `unknown` | BLOCK | |

- **Cross-checks (decided 17/10).** The LLM's name and namespace must equal the command's. Its effect must equal the part of the patch JSON that is touched. Its replicas must equal the patch's value. Any disagreement blocks. For this narrow form, the cross-check can read the answer from the JSON itself, so a translation error can only cause a block, never an approval. For verbs without such a check (the long tail), translation accuracy has to be measured instead (risk 2).
- **Blocked before the LLM is asked:** a patch to anything other than a deployment, a missing `-n`, JSON-patch (`--type=json`), or any other flag.
- **Failure paths.** No key, no model, a network error, a timeout (20 s) or an answer outside the schema all block.
- **Evidence.** Every raw answer is appended to `ARGUS_M3_LLM_LOG` (JSONL: time, model, command, raw text, token usage).
- **Prompt-tuned, not fine-tuned (D8, decided 17/10).** One fixed prompt plus a JSON schema. Fine-tuning is future work.
- **Model tier.** A cheap model for development and the demo. The final numbers should use a stronger one (NSVIF got worse with a small model).

## Open points
- PodDisruptionBudget as the source of the minimum was decided 17/10. A PDB limits voluntary disruptions; reading it as M3's minimum is our interpretation, and we need to be able to defend it.
- `-A` (all namespaces) can't be extracted one namespace at a time, so it blocks with an extractor error.
- Direct reads vs reads through M4 (RESEARCH_CONTEXT §5): proposed direct, read-only; needs team agreement and a check of SREGym's rules.
- The snapshot can change between the check and the write: record the snapshot time (or `resourceVersion`) and list it as a limitation.
- Model tier: develop on a cheap model; evaluate on a stronger one (NSVIF got worse with a small model).

## Objective → function → metric → evidence

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Check commands against live cluster state (FR-02, FR-03) | Extractor + Formulation Agent | Extraction latency; translation accuracy on a hand-checked set | Extractor tests; formulation results under `experiments/` | F1 template path; gate (b) | One non-template verb class (e.g. `patch`) for PP1 |
