# Function spec: M3 F2 — live constraints and LLM formulation

Status: Constraint Extractor built on saved kubectl output (W3-01); Formulation Agent planned (W3-02).

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
| `min_replicas` | The one PodDisruptionBudget whose selector picks the deployment's pods: its `minAvailable`, with a percentage rounded up (Kubernetes docs). No PDB, more than one, or a PDB with only `maxUnavailable` → unknown, so M3 blocks (fail-safe). A PDB with `matchExpressions` that might pick the pods (its `matchLabels` don't rule them out) also makes the minimum unknown. A PDB without a selector picks no pods; an empty selector `{}` picks all of them (policy/v1). |
| PVC `in_use` | A pod in the namespace mounts it (`spec.volumes[].persistentVolumeClaim.claimName`). |

- **Namespace check.** The namespace comes from the proposed command, so it must be a valid namespace name (a DNS-1123 label: at most 63 characters, `a-z`, `0-9` and `-`) before it goes into a read command. Otherwise text like `-n 'ns --server=https://other.example'` would add flags to the read. Anything else blocks before any read.
- **Gate.** With no snapshot passed in, the gate calls the extractor for the command's namespace and times it as the `extractor` stage. Any extractor error blocks, including a missing folder or a broken `index.json`. Pod and namespace deletes skip the extractor: their only rule (protected namespaces) needs no cluster facts.
- **Check against F1.** On five commands, the extractor-built facts and the hand-written snapshot give the same decisions (`test_gate.py`).

## Open points
- PodDisruptionBudget as the source of the minimum was decided 17/10. A PDB limits voluntary disruptions; reading it as M3's minimum is our interpretation, and we need to be able to defend it.
- `-A` (all namespaces) can't be extracted one namespace at a time. A PVC delete with `-A` blocks (not a valid namespace name); a pod delete with `-A` needs no facts and is blocked by the protected-namespace rule.
- Direct reads vs reads through M4 (RESEARCH_CONTEXT §5): proposed direct, read-only; needs team agreement and a check of SREGym's rules.
- The snapshot can change between the check and the write: record the snapshot time (or `resourceVersion`) and list it as a limitation.
- Model tier: develop on a cheap model; evaluate on a stronger one (NSVIF got worse with a small model).

## Objective → function → metric → evidence

| Objective | This function | Metric | Evidence | Baseline | Evaluation plan |
|---|---|---|---|---|---|
| Check commands against live cluster state (FR-02, FR-03) | Extractor + Formulation Agent | Extraction latency; translation accuracy on a hand-checked set | Extractor tests; formulation results under `experiments/` | F1 template path; gate (b) | One non-template verb class (e.g. `patch`) for PP1 |
