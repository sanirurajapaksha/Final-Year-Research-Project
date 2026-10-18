# Demo: one incident end to end

The incident is M1's `scenario_01`: the cart service is missing `CART_ADDR` (synthetic, after Stratus's example). It runs through the real M4, M1 and M3 code. **M2 is simulated** (`scenario.py`) until M2's `diagnose()` is ready. Nothing is executed on any cluster: M3 reads saved kubectl output, and M4's executor is a stub.

## Run it

From the repo root, after `pip install -e ".[dev,eval,demo]"`:

```bash
python -m argus.demo                          # prints the run; add --save run.json to keep it
python -m streamlit run src/argus/demo/app.py # the same run as a web page (http://localhost:8501)
```

Round 2's fix is a `kubectl patch`, which M3 reads with its LLM Formulation Agent. That needs an OpenRouter key in `ARGUS_LLM_API_KEY`. Copy `.env.example` to `.env` in the repo root and put the key there; `.env` is git-ignored, and both commands read it. Without a key, M3 blocks the patch (fail-closed), and the page and printout say why.

## What you should see

- **Round 1:** M2 proposes `kubectl scale deployment cart --replicas=0 -n default`. M3 **blocks** it, with the counterexample before 1 → after 0 against a minimum of 1 (cart's PodDisruptionBudget). The verdict goes back to M2.
- **Round 2:** M2 proposes the fix, a patch adding `CART_ADDR`. The LLM reads it as a pod-template change, so M3 checks it as a rolling update. With 1 replica and the default 25% limits, the new pod starts before the old one stops, so M3 **approves** it.

## Files

| File | What it does |
|---|---|
| `run.py` | `run_demo()`: runs the incident and returns everything as plain data |
| `scenario.py` | The simulated M2 (labelled). It will be replaced by M2's `diagnose()` |
| `__main__.py` | Prints the run |
| `app.py` | The team dashboard's first page: the whole run |
| `pages/` | One page per module, each owned by its member: `1_M1_context.py` (Minidu), `2_M2_diagnosis.py` (Kaveen), `3_M3_safety.py` (Saniru), `4_M4_orchestration.py` (Nethmi). M1, M2 and M4 are placeholders for now; they show their module's part of the same run |
| `views.py` | Display helpers the pages share (no module logic) |
