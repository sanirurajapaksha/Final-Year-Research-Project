# Demo: one incident through the whole agent

One page, drawn like a CI pipeline. Choose a sample incident or upload a telemetry file, press **Run**, and each stage card fills in as its module finishes:

```
Telemetry → M4 Compress → M1 Context → M2 Diagnose → Formal Verification → M2 Feedback → M4 Execute
```

Under the pipeline, each stage opens to show how that module decided: M1's service graph and pruned signals, M2's hypotheses and belief after every read, the safety layer's verdict, counterexample and the cluster facts it read, and what M4 did with each action.

The **Formal Verification** stage (the Proactive Formal Verification Safety Layer) also draws its own steps for each write, in order:

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
| **Cart keeps crashing, out of memory** (`data/fixtures/demo/scenario_02/`, namespace `shop`) | M1 keeps 9 of 12 signals. M2's reads confirm "OOMKilled / crash-looping" (85%) and it proposes a rolling restart. In `shop`, cart has 2 replicas and needs 2 available, and a restart takes 1 down, so the safety layer **blocks** it with that counterexample. M2 knows no other safe fix, so the incident goes to a human. |

To try another incident, download a sample's telemetry from the sidebar, edit it, and upload it. The flow is the same; what happens depends on the data. M2 only has canned read results for the two samples, so for a new incident it usually stops as not confident and proposes no fix.

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
