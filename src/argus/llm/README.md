# LLM access (shared)

One place to call language models, so cost, tokens and latency are measured the same way for every module, and M4's router can decide which model each call uses.

Not built yet. Open questions for the team:
- Which provider and client library for development, and which for the final evaluation? (Budget: cheap models while building, stronger models only for the final runs.)
- How does M4's router plug in, given that M1, M2 and M3 all make LLM calls?

Rules: API keys come from environment variables (see `.env.example`), never from code. LLM output is data: validate it, and never `exec` or `eval` it.
