# M2 LLM steps against a real model (21 Oct 2026)

**What:** the checks from `tests/integration/test_m2_llm_live.py`, repeated, plus the dashboard's path end to end with the LLM on. Each call's raw reply, tokens and status are kept.

**Why:** review on #42. The live figures in that PR had no raw files behind them. It also answers the review question about the team model: the same run on the model in `.env.example`.

**Code:** commit `0c54801` (branch `feat/m2-llm-generator`). Nothing tracked was modified at run time; `scripts/run_m2.py` was untracked. Prompt versions: score-v2, draft-v2, fix-v3, report-v1 (`config.json` in each results folder).

**Data:**
- `data/fixtures/m2/contexts/cart_addr.json`: M1's F2 output for scenario_01
- `data/fixtures/m2/scenario_01/reads.json`: canned kubectl output

Both are hand-written (synthetic). A read M2 asks for that isn't in `reads.json` fails, exactly as on the dashboard. **No cluster, nothing executed.**

**Commands** (run from the repository root, with `ARGUS_LLM_API_KEY` set):
```
python experiments/2026-10-21_m2_llm_live/run.py --model deepseek/deepseek-v4-flash-0731
python experiments/2026-10-21_m2_llm_live/run.py --model google/gemini-2.5-flash-lite
```
The defaults are 3 runs per check and 5 for the fix. In score, each run judges 3 reads.

## Results

| Check | What passes | deepseek-v4-flash-0731 | gemini-2.5-flash-lite |
|---|---|---|---|
| score | the verdict on the read's hypothesis matches RuleScorer | 9/9 | 9/9 |
| draft | the LLM's hypotheses include cart / app-config | 3/3 | 3/3 |
| fix | an LLM fix that is exactly the `CART_ADDR=redis-cart:6379` patch | 5/5, 2 tries each | 4/5, 1 try each |
| report | the LLM note passes the checks (real ids, names cart, ≤120 words) | 3/3 | 3/3 |
| end to end | the same write as rules mode | **0/3** | **0/3** |

Raw files are in `results/<model>/`:
- `summary.json`, `config.json`
- one JSON file per check
- `llm_calls.jsonl`: every call with task, prompt version, prompt hash, tokens, status and raw reply
- `trajectories.jsonl`: the end-to-end loops, from `run_logged`

## What I observed

- **Fix, deepseek:** the first answer was `CART_ADDR=cart:7070` (cart pointed at itself) in all 5 runs. The host check sent it back naming redis, and the second try gave `redis-cart:6379`.
- **Fix, gemini:** right on the first try in all 4 completed runs. The 5th fix call got HTTP 429 (rate limit) from OpenRouter, so the step fell back to the rule fix. The check counts that as a fail because the source is not the LLM.
- **End to end, both models: 0/3, and the cause is the canned data, not the logic.**
  - deepseek: the right hypothesis, cart / app-config, ended at 78.6–78.9% in all three runs, just under the 0.80 stop line. Its other checks (`endpoints redis`, `logs deployment/frontend`) are not in `reads.json`, so they failed and counted as neutral. That leaves the loop "out of hypotheses" with no write, which is the intended behaviour when the reads don't confirm.
  - gemini: it chose checks that `reads.json` can't answer at all (a `jsonpath` query on the pods, `logs deployment/redis`), so it only reached 48%.
  - An earlier manual run on 20 Oct (not saved) once reached the stop line with deepseek, so this result varies between runs.
  - Testing the LLM path end to end needs a real cluster, or a fake cluster that answers more than a fixed list of commands.
- **The `reasoning` setting** (thinking low for score, off for the other steps) was accepted for both models: no routing errors. The settings were tuned on deepseek on 20 Oct; gemini worked with them unchanged.
- **Tokens per end-to-end run:** about 6.0k in and 1.6–1.9k out on deepseek (6 calls), and about 3.5k in and 1.5k out on gemini (5 calls).

## Limits

- One scenario, hand-written, with n = 3 or 5 per check. These are smoke checks of the LLM path, not accuracy figures.
- The clue table and the prompts' rules were written with scenario_01 in view, so passing here mostly shows that they fit this case.
