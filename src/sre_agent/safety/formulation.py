"""Step 2a: Formulation Agent.

Turns a command into a typed, schema-validated intermediate representation (verb, target,
effect, pre-conditions). Common kubectl verbs (scale, delete, rollout) should use
deterministic templates; the LLM handles the long tail.

LLM output is data: validate it against a schema, and never exec or eval it in this process.
"""

from typing import Any


def formulate(command: str) -> dict[str, Any]:
    """Return the intermediate representation of `command`."""
    raise NotImplementedError("Formulation Agent not implemented yet")
