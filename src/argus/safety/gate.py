"""M3 entry point: decide APPROVE or BLOCK for one write command.

Pipeline:
    0. prefilter.py  syntactic checks, no LLM
    1. extractor.py  cluster facts from read-only kubectl output (saved output now, a live cluster later),
       snapshot.py   unless the caller passes a snapshot; then the target's facts are looked up
    2. parser.py     command -> structured action (templates for scale, delete, rollout restart)
       formulation.py  the LLM path for commands the parser can't read (v0: kubectl patch)
       compiler.py   action + facts -> Z3 constraints, solved inside the worker
    3. sandbox.py    runs the worker in a subprocess with a timeout (and CPU/memory limits on Linux)

Z3 is asked about the NEGATED safety property, so its raw answer maps to the decision like this:
    unsat                          -> APPROVE (no counterexample with respect to the encoded invariants)
    sat                            -> BLOCK, and the model is the counterexample
    unknown, timeout, error, none  -> BLOCK (fail-closed)

The raw result (`z3_result`) and the decision (`decision`) are separate fields of SafetyVerdict.
Every early exit also BLOCKs, and its `reason` names the stage that stopped the command.
"""

from pathlib import Path
from typing import Any

from argus.common.timing import stage_timer
from argus.config import Settings, load_settings
from argus.contracts import GateDecision, ProposedAction, SafetyVerdict, Z3Result
from argus.safety import extractor, formulation, parser, prefilter, sandbox
from argus.safety.policy import PROTECTED_NAMESPACES
from argus.safety.snapshot import facts_for


def _fact_source(settings: Settings) -> extractor.Runner:
    """Where the extractor reads cluster facts: saved kubectl output (PP1), or the live dev cluster."""
    if settings.m3_kubectl_output:
        return extractor.saved_output(Path(settings.m3_kubectl_output))
    return extractor.live_kubectl(settings.kube_context)


def decision_for(z3_result: Z3Result | None) -> GateDecision:
    """Map Z3's raw result on the negated safety property to the gate decision."""
    if z3_result is Z3Result.UNSAT:
        return GateDecision.APPROVE
    return GateDecision.BLOCK


def check(
    action: ProposedAction,
    snapshot: dict[str, Any] | None = None,
    settings: Settings | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> SafetyVerdict:
    """Check one write command against the cluster facts in `snapshot`.

    Without a `snapshot`, the extractor reads the facts from the source in `settings`
    (saved kubectl output or the live cluster). With neither, every deployment or PVC command
    is blocked; pod and namespace deletes need no facts.

    If a `trace` list is given, each step appends what it did, for the dashboard:
    {"step", "status" (passed, skipped or stopped), "summary", "data", "ms"}. The verdict is the same.
    """
    settings = settings or load_settings()
    timings: dict[str, float] = {}

    def note(step: str, status: str, summary: str, data: Any = None, ms: float | None = None) -> None:
        if trace is not None:
            trace.append({"step": step, "status": status, "summary": summary, "data": data, "ms": ms})

    # Helper function
    def block(reason: str) -> SafetyVerdict:
        note("Decision", "stopped", "BLOCK: " + reason)
        return SafetyVerdict(
            command=action.command, decision=GateDecision.BLOCK, reason=reason, timings_ms=timings
        )

    with stage_timer(timings, "prefilter"):
        rejection = prefilter.check(action.command)
    if rejection is not None:
        note("Pre-filter", "stopped", rejection, ms=timings["prefilter"])
        return block(f"pre-filter: {rejection}")
    tokens = prefilter.tokenize(action.command)
    note("Pre-filter", "passed", "one plain kubectl command, no shell syntax", tokens, timings["prefilter"])

    with stage_timer(timings, "parse"):
        try:
            parsed = parser.parse(action.command)
        except parser.ParseError as exc:
            parsed, parse_error = None, str(exc)

    # Commands the fixed parser can't read (v0: kubectl patch) go to the LLM Formulation Agent.
    if parsed is None and formulation.handles(action.command):
        note("Parse", "skipped", "not a template command, so the LLM reads it", ms=timings["parse"])
        with stage_timer(timings, "formulation"):
            try:
                parsed = formulation.formulate(action.command, settings.llm_model, settings.m3_llm_log)
            except (formulation.FormulationError, parser.ParseError) as exc:
                formulation_error = str(exc)
        if parsed is None:
            note("LLM formulation", "stopped", formulation_error, ms=timings["formulation"])
            return block(f"formulation: {formulation_error} (fail-closed)")
        summary = f"the LLM's answer matches the command text; checked as {parsed.verb} {parsed.kind}"
        note("LLM formulation", "passed", summary, parsed.to_request(), timings["formulation"])
    elif parsed is None:
        note("Parse", "stopped", parse_error, ms=timings["parse"])
        return block(f"parse: {parse_error}")
    else:
        summary = f"{parsed.verb} {parsed.kind} {parsed.namespace}/{parsed.name}"
        note("Parse", "passed", summary, parsed.to_request(), timings["parse"])

    # Protected namespaces go on to the solver (I2 gives the counterexample). Any other namespace
    # delete removes everything inside it, which F1 doesn't model, so it is blocked here.
    if parsed.kind == "namespace" and parsed.name not in PROTECTED_NAMESPACES:
        return block(
            f"deleting namespace {parsed.name!r} deletes everything in it; not modelled in F1 (fail-closed)"
        )

    # Pods and namespaces: their only F1 rule (protected namespaces) needs no cluster facts,
    # so they skip the extractor and keep the protected_namespace counterexample.
    if snapshot is None and parsed.kind not in ("deployment", "pvc"):
        snapshot = {}
        note("Cluster facts", "skipped", "pods and namespaces need no cluster facts")

    # No snapshot passed in: the extractor builds one for the command's namespace.
    if snapshot is None:
        if not settings.m3_kubectl_output and not settings.kube_context:
            return block(
                "no cluster snapshot and no fact source "
                "(set ARGUS_M3_KUBECTL_OUTPUT or ARGUS_KUBE_CONTEXT) (fail-closed)"
            )
        with stage_timer(timings, "extractor"):
            try:
                # Opening the source is inside the try too: a missing folder or a broken index.json blocks.
                snapshot = extractor.extract(parsed.namespace, _fact_source(settings))
            except Exception as exc:  # any extractor failure blocks; it never approves
                snapshot, extract_error = None, f"{type(exc).__name__}: {exc}"
        if snapshot is None:
            note("Cluster facts", "stopped", extract_error, ms=timings["extractor"])
            return block(f"extractor: {extract_error} (fail-closed)")

    with stage_timer(timings, "facts"):
        facts = facts_for(snapshot, parsed.kind, parsed.namespace, parsed.name)
    if facts is None:
        note("Cluster facts", "stopped", f"{parsed.kind} {parsed.namespace}/{parsed.name} isn't there")
        return block(f"resource not in snapshot: {parsed.kind} {parsed.namespace}/{parsed.name}")
    if parsed.kind in ("deployment", "pvc"):
        read_ms = timings.get("extractor", 0.0) + timings["facts"]
        note(
            "Cluster facts", "passed", f"read-only facts for {parsed.namespace}/{parsed.name}", facts, read_ms
        )

    request = {
        "action": parsed.to_request(),
        "facts": facts,
        "timeout_ms": sandbox.z3_timeout_ms(settings.solver_timeout_s),
    }
    with stage_timer(timings, "sandbox_total"):
        outcome = sandbox.run(request, settings.solver_timeout_s, settings.solver_memory_mb)
    if outcome.result is None:
        note("Logic compiler + Z3", "stopped", outcome.error, ms=timings["sandbox_total"])
        return block(f"solver: {outcome.error} (fail-closed)")

    result = outcome.result
    timings["solver"] = float(result.get("solver_ms", 0.0))
    if result.get("error"):
        note("Logic compiler + Z3", "stopped", result["error"], ms=timings["sandbox_total"])
        return block(f"solver: {result['error']} (fail-closed)")

    try:
        z3_result = Z3Result(result["z3_result"])
    except (KeyError, ValueError):
        return block(f"solver: unexpected result {result.get('z3_result')!r} (fail-closed)")

    solved = {
        "z3_result": z3_result.value,
        "formula": result.get("formula"),
        "checked_invariants": result.get("checked_invariants", []),
        "counterexample": result.get("counterexample"),
        "solver_ms": timings["solver"],
    }
    note("Logic compiler + Z3", "passed", f"z3 answered {z3_result.value}", solved, timings["sandbox_total"])

    decision = decision_for(z3_result)
    reason = _reason(z3_result, result)
    if decision is GateDecision.APPROVE:
        note("Decision", "passed", "APPROVE: " + reason)
    else:
        note("Decision", "stopped", "BLOCK: " + reason)
    return SafetyVerdict(
        command=action.command,
        z3_result=z3_result,
        decision=decision,
        reason=reason,
        violated_invariants=result.get("violated_invariants", []),
        counterexample=result.get("counterexample"),
        timings_ms=timings,
    )


def _reason(z3_result: Z3Result, result: dict[str, Any]) -> str:
    if z3_result is Z3Result.UNSAT:
        checked = ", ".join(result.get("checked_invariants", []))
        text = f"no post-state violates the encoded invariants ({checked})"
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
