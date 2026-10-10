# Contributing

## Branches and pull requests
- Never commit straight to `main`. Branch, push, open a PR, and get one teammate's review.
- Branch names: `feat/<module>-<short-name>`, `fix/...`, `docs/...`, `chore/...` (e.g. `feat/m3-prefilter`).
- Keep commits small, with messages that say what changed. Mention the Planner task ID (e.g. `W2-03`) in the PR.
- Fill in the PR template, including the AI-assistance section.

## Module ownership
- Each module folder has an owner (see the README). Change someone else's module only after they agree.
- `src/sre_agent/contracts/` is shared. A PR that changes it needs approval from every owner whose module sends or receives the changed model.

## Tests
- Every function gets at least one **happy-path** and one **failure-path** test.
- Unit tests go in `tests/unit/<module>/`; tests that span modules go in `tests/integration/`.
- CI runs `ruff` and `pytest` on every push. Keep it green.

## Safety
- **No secrets in the repo:** API keys go in `.env` (git-ignored) or environment variables. Never commit kubeconfigs.
- **Cluster changes:** run mutating `kubectl`, `helm` or `kind` commands only against the disposable dev cluster, and check `kubectl config current-context` first.
- **LLM output is data.** Validate it; never `exec` or `eval` it.
- Writes reach a cluster only through M4's execution handler, after M3 approves them.

## Evidence
- Raw results are research evidence: put them under `experiments/` and never edit them by hand.
- Record AI use in your PR and in your own logbook: the tool, what it produced, how you checked it, and what you changed.

## Style
- Python 3.12+, formatted and linted with `ruff` (`ruff format .`, `ruff check .`).
- Add a dependency only after the team agrees, and pin its exact version in `pyproject.toml`.
