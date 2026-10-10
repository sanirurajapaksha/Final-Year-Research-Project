"""M3's output: the safety gate's answer for one write command (M3 -> M4, and M3 -> M2 on BLOCK)."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class Z3Result(StrEnum):
    """Z3's raw answer on the NEGATED safety formula.

    `sat` means Z3 found a counterexample (the command is unsafe in the encoded model);
    `unsat` means no counterexample exists in the encoded model.
    """

    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"


class GateDecision(StrEnum):
    APPROVE = "APPROVE"
    BLOCK = "BLOCK"


class SafetyVerdict(BaseModel):
    """The raw solver result and the gate decision are separate fields on purpose."""

    command: str
    # None when M3 decided before reaching the solver (pre-filter rejection, timeout, error).
    z3_result: Z3Result | None = None
    decision: GateDecision
    reason: str
    violated_invariants: list[str] = []
    counterexample: dict[str, Any] | None = None
    # Milliseconds per stage: prefilter, extractor, formulation, solver.
    timings_ms: dict[str, float] = {}
