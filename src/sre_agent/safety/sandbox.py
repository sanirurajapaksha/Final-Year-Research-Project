"""Step 3: sandboxed Z3 runtime.

Runs a generated script in a separate subprocess with a CPU timeout and a memory cap
(see Settings.solver_timeout_s and Settings.solver_memory_mb), and returns Z3's raw answer
plus the model when the answer is `sat`. A timeout or crash returns no result, which the
gate treats as BLOCK.
"""

from typing import Any

from sre_agent.contracts import Z3Result


def run(script: str, timeout_s: float, memory_mb: int) -> tuple[Z3Result | None, dict[str, Any] | None]:
    """Return (raw Z3 result or None on timeout/error, counterexample model or None)."""
    raise NotImplementedError("Sandbox not implemented yet")
