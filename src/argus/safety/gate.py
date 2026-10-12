"""M3 entry point: decide APPROVE or BLOCK for one write command.

Pipeline:
    0. prefilter.py  syntactic checks, no LLM
    1. snapshot.py   facts about the target (F1: fixture; F2: extractor.py reads the live cluster)
    2. parser.py     command -> structured action (templates; formulation.py adds the LLM path in F2)
       compiler.py   action + facts -> Z3 constraints, solved inside the worker
    3. sandbox.py    runs the worker in a subprocess with a timeout (and CPU/memory limits on Linux)

Z3 is asked about the NEGATED safety property, so its raw answer maps to the decision like this:
    unsat                          -> APPROVE (no counterexample with respect to the encoded invariants)
    sat                            -> BLOCK, and the model is the counterexample
    unknown, timeout, error, none  -> BLOCK (fail-closed)

The raw result (`z3_result`) and the decision (`decision`) are separate fields of SafetyVerdict.
Every early exit also BLOCKs, and its `reason` names the stage that stopped the command.
"""

from typing import Any

from argus.common.timing import stage_timer
from argus.config import Settings, load_settings
from argus.contracts import GateDecision, ProposedAction, SafetyVerdict, Z3Result
from argus.safety import parser, prefilter, sandbox
from argus.safety.snapshot import deployment_facts


def decision_for(z3_result: Z3Result | None) -> GateDecision:
    """Map Z3's raw result on the negated safety property to the gate decision."""
    if z3_result is Z3Result.UNSAT:
        return GateDecision.APPROVE
    return GateDecision.BLOCK


def check(
    action: ProposedAction,
    snapshot: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> SafetyVerdict:
    """Check one write command against the cluster facts in `snapshot`.

    `snapshot` is optional so existing callers keep working: without one (until the live
    extractor exists) every command is blocked.
    """
    settings = settings or load_settings()
    timings: dict[str, float] = {}

    def block(reason: str) -> SafetyVerdict:
        return SafetyVerdict(
            command=action.command, decision=GateDecision.BLOCK, reason=reason, timings_ms=timings
        )

    with stage_timer(timings, "prefilter"):
        rejection = prefilter.check(action.command)
    if rejection is not None:
        return block(f"pre-filter: {rejection}")

    with stage_timer(timings, "parse"):
        try:
            parsed = parser.parse(action.command)
        except parser.ParseError as exc:
            parsed, parse_error = None, str(exc)
    if parsed is None:
        return block(f"parse: {parse_error}")

    if snapshot is None:
        return block("no cluster snapshot: the live Constraint Extractor isn't built yet (fail-closed)")

    with stage_timer(timings, "facts"):
        facts = deployment_facts(snapshot, parsed.namespace, parsed.name)
    if facts is None:
        return block(f"resource not in snapshot: deployment {parsed.namespace}/{parsed.name}")

    request = {
        "action": parsed.to_request(),
        "facts": facts,
        "timeout_ms": sandbox.z3_timeout_ms(settings.solver_timeout_s),
    }
    with stage_timer(timings, "sandbox_total"):
        outcome = sandbox.run(request, settings.solver_timeout_s, settings.solver_memory_mb)
    if outcome.result is None:
        return block(f"solver: {outcome.error} (fail-closed)")

    result = outcome.result
    timings["solver"] = float(result.get("solver_ms", 0.0))
    if result.get("error"):
        return block(f"solver: {result['error']} (fail-closed)")

    try:
        z3_result = Z3Result(result["z3_result"])
    except (KeyError, ValueError):
        return block(f"solver: unexpected result {result.get('z3_result')!r} (fail-closed)")

    decision = decision_for(z3_result)
    return SafetyVerdict(
        command=action.command,
        z3_result=z3_result,
        decision=decision,
        reason=_reason(z3_result, result),
        violated_invariants=result.get("violated_invariants", []),
        counterexample=result.get("counterexample"),
        timings_ms=timings,
    )


def _reason(z3_result: Z3Result, result: dict[str, Any]) -> str:
    if z3_result is Z3Result.UNSAT:
        text = "no post-state violates the encoded invariants (min_replicas, replicas_in_int32_range)"
    elif z3_result is Z3Result.SAT:
        text = f"counterexample found: violates {', '.join(result.get('violated_invariants', []))}"
    else:
        text = "solver returned unknown (fail-closed)"

    notes = []
    if result.get("pre_state_violations"):
        notes.append(f"already violated before the command: {', '.join(result['pre_state_violations'])}")
    if result.get("missing_facts"):
        notes.append(f"missing facts left unconstrained: {', '.join(result['missing_facts'])}")
    return text + (f" [{'; '.join(notes)}]" if notes else "")
