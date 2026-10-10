"""M3 entry point: decide APPROVE or BLOCK for one write command.

Pipeline (one file per step):
    0. prefilter.py   syntactic checks, no LLM
    1. extractor.py   read-only cluster queries -> invariants and current state
    2. formulation.py LLM -> typed intermediate representation of the command
       compiler.py    representation + invariants -> Z3 script
    3. sandbox.py     run the script in a subprocess with a timeout and a memory cap

Z3 is asked about the NEGATED safety formula, so its raw answer maps to the decision like this:
    unsat                         -> APPROVE (no counterexample in the encoded model)
    sat                           -> BLOCK, and the model is the counterexample
    unknown, timeout, error, none -> BLOCK (fail-closed)
"""

from sre_agent.common.timing import stage_timer
from sre_agent.contracts import GateDecision, ProposedAction, SafetyVerdict, Z3Result
from sre_agent.safety import prefilter


def decision_for(z3_result: Z3Result | None) -> GateDecision:
    """Map Z3's raw result on the negated safety formula to the gate decision."""
    if z3_result is Z3Result.UNSAT:
        return GateDecision.APPROVE
    return GateDecision.BLOCK


def check(action: ProposedAction) -> SafetyVerdict:
    """Check one write command.

    STUB: only step 0 runs. Steps 1-3 aren't built yet, so every command that passes the
    pre-filter is still blocked (fail-closed).
    """
    timings: dict[str, float] = {}

    with stage_timer(timings, "prefilter"):
        rejection = prefilter.check(action.command)
    if rejection is not None:
        return SafetyVerdict(
            command=action.command,
            decision=GateDecision.BLOCK,
            reason=f"pre-filter: {rejection}",
            timings_ms=timings,
        )

    return SafetyVerdict(
        command=action.command,
        z3_result=None,
        decision=decision_for(None),
        reason="stub: solver path not implemented yet (fail-closed)",
        timings_ms=timings,
    )
