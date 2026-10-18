# LLM access (shared)

One place to call language models, so cost, tokens and latency are measured the same way for every module, and M4's router can decide which model each call uses.

**Built (17/10, first user: M3's Formulation Agent):** `client.complete_json(prompt, schema, model)` sends one prompt to **OpenRouter** and returns `(json_text, usage)`. The answer must match the JSON Schema you pass (OpenRouter structured outputs). Any problem (no key, network, timeout, an unexpected reply) raises `LLMError`.

- Key: `ARGUS_LLM_API_KEY`, from the environment. The command-line entry points and the demo page first load the git-ignored `.env` in the repo root (python-dotenv), so the key can live there; see `.env.example`.
- Model: `ARGUS_LLM_MODEL`. Development and demo use `google/gemini-2.5-flash-lite`. Stronger models are for the final evaluation only.
- No new dependency: it uses Python's `urllib`.
- Limits: `timeout_s` (default 20 s) covers the whole call; `max_tokens` (default 300) caps the answer. Reasoning models may need a higher cap.
- Privacy: the prompt is sent to OpenRouter as it is. Don't put secrets in prompts; nothing is redacted.

Still open for the team:
- Which models to use for the final evaluation.
- How M4's router plugs in, given that M1, M2 and M3 all make LLM calls. `complete_json` takes the model as an argument, so the router can choose it.

Rules: API keys come from environment variables (see `.env.example`), never from code. LLM output is data: validate it, and never `exec` or `eval` it.
