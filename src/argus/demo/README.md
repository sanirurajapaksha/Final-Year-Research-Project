# Demo: one incident through the whole agent

One page, drawn like a CI pipeline. Choose a sample incident or upload a telemetry file, press **Run**, and each stage card fills in as its module finishes:

```
Telemetry → Prepare Telemetry → Build Context → Diagnose Cause → Verify Safety → Revise Plan → Execute Action
```

Under the pipeline, each stage opens to show how it reached its result. Context Analysis shows the service graph and pruned signals. Root Cause Diagnosis has three tabs: **Belief & Evidence** compares starting and final belief and shows the diagnostic reads; **Diagnosis Summary** explains the leading hypothesis and its read assessments; **Fixes** lists proposed commands and their review status. Safety Verification shows the verdict, counterexample and cluster facts. Action Orchestration shows how it handled each action.

The **Verify Safety** stage (the Proactive Formal Verification Safety Layer) also draws its own steps for each write, in order:

```
Pre-filter → Parse (or LLM formulation for a patch) → Cluster facts → Logic compiler + Z3 → Decision
```

- A red step is where checking stopped (fail-closed).
- Each step opens to show its real data: the command's words, the parsed action, the facts read, the exact formula Z3 was asked (facts, what the command does, the rules) with Z3's answer, and the counterexample.
- The same panel has **Try another command**, with example buttons for the main cases: a scale below the minimum, a safe scale, a restart Z3 has to search, a protected namespace, a shell trick, and a patch read by the LLM.
- The steps come from `gate.check(..., trace=[])`; the verdict is the same with or without a trace.

## Run it

From the repo root, after `pip install -e ".[dev,eval,demo]"`:

```bash
python -m streamlit run src/argus/demo/app.py
```

```bash
python -m argus.demo --scenario 2
```

The first opens the page at http://localhost:8501. The second prints the same stages (`--scenario 1` or `2`, or `--telemetry FILE`; add `--save run.json` to keep the run).

Scenario 1's fix is a `kubectl patch`, which the safety layer reads with its LLM Formulation Agent: one LLM call per run. It needs an OpenRouter key in `ARGUS_LLM_API_KEY`. Copy `.env.example` to `.env` in the repo root and put the key there (git-ignored; both commands read it). Without a key, the patch is blocked (fail-closed), and the page says why.

## The sample incidents

| Incident | What happens |
|---|---|
| **Cart can't reach its cache** (M1's `scenario_01`, namespace `default`) | M1 keeps 5 of 8 signals. M2's reads confirm "CART_ADDR missing" (85%) and it proposes a patch adding it. The LLM reads the patch as a pod-template change; Z3 finds no end state that breaks a rule, so the safety layer **approves**. |
| **Cart keeps crashing, out of memory** (`data/fixtures/demo/scenario_02/`, namespace `shop`) | M1 keeps 9 of 12 signals. M2's reads confirm "OOMKilled / crash-looping" (85%) and it proposes a rolling restart. In `shop`, cart has 2 replicas and needs 2 available, and a restart takes 1 down, so the safety layer **blocks** it with that counterexample. M2 reads the counterexample and proposes scaling cart to 3 replicas first, so the restart keeps 2 available; the safety layer **approves** the scale-up. |
| **Hotel search fails, MongoDB disk full** (`data/fixtures/demo/scenario_03/`, namespace `hotel-reservation`) | mongodb-geo sends no spans, but it crash-loops and geo's error names it, so M2 makes it the origin. Its reads confirm "data volume full" (84%): the last logs show "No space left on device", and the crash was not an OOMKill. A restart would crash again on the same full disk, so M2 hands a person the PVC expansion command (`kubectl patch pvc geo-pvc ...`). The demo still sends that command to the safety layer, labelled `FOR A HUMAN`; it has no rule for a PVC patch yet, so it **blocks** it, M2 has no other fix, and the incident goes to a human with M2's recommendation. |

To try another incident, download a sample's telemetry from the sidebar, edit it, and upload it. The flow is the same; what happens depends on the data. M2 only has canned read results for the three samples, so for a new incident it usually stops as not confident and proposes no fix.

The page and the command still run the safety layer and M4 on such an incident: the demo turns M2's tentative fixes on (elsewhere they stay off unless `ARGUS_M2_TENTATIVE_FIXES=1` is set). M2 then sends its best guess's fix to the safety layer even though the reads did not confirm it, with `TENTATIVE (unconfirmed, NN%)` at the start of the fix's rationale and in M2's report; a guess below "none of these" or below 30% is sent too, labelled `TENTATIVE (low confidence, NN%)`. When no command fixes the cause (a code bug, a fault with no fix template), M2 sends a restart labelled `FOR A HUMAN` and "stopgap only", so the flow still runs and a person decides. The safety layer checks these like any other fix, and the M4 stage says when an approved fix awaits a person. M4 itself cannot tell a labelled fix from a confirmed one, so an approved one reaches the executor: keep the switch off anywhere the executor is not the PP1 stub.

## What is real and what is simulated

- **Real:** the code of all four modules, Z3, and the LLM call.
- **Simulated (no cluster in PP1):**
  - the telemetry (synthetic, or uploaded);
  - the results of M2's reads (canned kubectl output in `reads.json`);
  - the safety layer's cluster facts (saved kubectl output in `data/fixtures/m3/kubectl/`);
  - the executor (a stub: nothing is run).

  The page says this in its sidebar.

## Files

| File | What it does |
|---|---|
| `flow.py` | The run: one function per stage, each calling the real module code and returning plain data. The sample incidents are listed here |
| `app.py` | The page: draws the pipeline as `flow.py` yields each stage, then each stage's details |
| `__main__.py` | The same run on the command line |
| `run.py` | The demo's settings (saved kubectl output, default model) |
| `views.py` | How the pipeline cards, the safety layer's steps and its verdict are drawn |
