"""Step 0: syntactic pre-filter (no LLM).

Rejects command shapes M3 can't reason about, such as pipes, compound commands (&&, ||, ;),
command substitution, and interactive or stdin forms. Starting rule list: Stratus App. A, Table 5.
"""


def check(command: str) -> str | None:
    """Return a rejection reason, or None if the command may continue to the solver path.

    STUB: accepts every command. The gate still blocks it later, because steps 1-3 don't exist yet.
    """
    return None
