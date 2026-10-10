"""Step 2b: Logic Compiler.

Builds the Z3 script for F = I(S0) and T(S0, A, S1) and not I(S1) from the intermediate
representation and the extracted invariants. The script is run by sandbox.py, never in-process.
"""

from typing import Any


def compile_script(representation: dict[str, Any], snapshot: dict[str, Any]) -> str:
    """Return the source of a standalone Python script that uses z3-solver."""
    raise NotImplementedError("Logic Compiler not implemented yet")
