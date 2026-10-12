"""Step 2b: Logic Compiler. Turns (action, cluster facts) into Z3 constraints and solves them.

Encodings here are hand-written templates, not generated code. They run inside the sandboxed
worker (worker.py), so a solver hang or crash can't take the agent down.

Formula. For a command A with transition T and invariants I, Z3 is asked whether

    Facts(S0) and T(S0, A, S1) and not I(S1)

is satisfiable. Facts(S0) are the values read from the cluster snapshot; any fact that is missing
stays unconstrained, so Z3 may choose a value for it that breaks an invariant (fail-safe).

    sat     -> a reachable post-state breaks an invariant; the model is the counterexample (BLOCK)
    unsat   -> no post-state breaks an encoded invariant (APPROVE, with respect to these invariants)
    unknown -> undecided (BLOCK)

I(S0) is NOT assumed. During an incident the cluster often already breaks an invariant; assuming
I(S0) would then make the formula unsatisfiable and approve every command (vacuous truth).
Instead, invariants that already fail before the command are reported separately.
Before the main check, Facts and T are checked for consistency: if they contradict each other the
main check would also be vacuously unsat, so that case is an error (BLOCK), never an APPROVE.

F1 slice: one verb (scale) and one invariant family (minimum replicas).
"""

import time
from typing import Any

import z3

INT32_MAX = 2**31 - 1


class EncodingError(ValueError):
    """The request can't be encoded (unsupported action or malformed facts)."""


def solve(request: dict[str, Any]) -> dict[str, Any]:
    """Encode and solve one request. Returns a JSON-serialisable result.

    request = {"action": {...}, "facts": {...}, "timeout_ms": int}
    """
    action = request["action"]
    facts = request.get("facts", {})
    timeout_ms = int(request.get("timeout_ms", 5000))

    if action.get("verb") == "scale" and action.get("kind") == "deployment":
        return _solve_scale(action, facts, timeout_ms)
    raise EncodingError(f"no encoding for {action.get('verb')!r} on {action.get('kind')!r}")


def _fact(facts: dict[str, Any], key: str) -> int | None:
    value = facts.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise EncodingError(f"fact {key!r} must be an integer, got {value!r}")
    if not 0 <= value <= INT32_MAX:
        raise EncodingError(f"fact {key!r} is outside the Kubernetes int32 range: {value}")
    return value


def _replica_invariants(replicas: z3.ArithRef, min_replicas: z3.ArithRef) -> dict[str, z3.BoolRef]:
    return {
        "replicas_in_int32_range": z3.And(replicas >= 0, replicas <= INT32_MAX),
        "min_replicas": replicas >= min_replicas,
    }


def _solve_scale(action: dict[str, Any], facts: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
    target = action["params"]["replicas"]
    if isinstance(target, bool) or not isinstance(target, int):
        raise EncodingError(f"replicas must be an integer, got {target!r}")
    known_replicas = _fact(facts, "replicas")
    known_min = _fact(facts, "min_replicas")

    replicas_before = z3.Int("replicas_before")
    replicas_after = z3.Int("replicas_after")
    min_replicas = z3.Int("min_replicas")

    # Facts(S0): values from the snapshot, plus the domain every Kubernetes value obeys.
    state_facts = [
        replicas_before >= 0,
        replicas_before <= INT32_MAX,
        min_replicas >= 0,
        min_replicas <= INT32_MAX,
    ]
    if known_replicas is not None:
        state_facts.append(replicas_before == known_replicas)
    if known_min is not None:
        state_facts.append(min_replicas == known_min)

    # T(S0, A, S1): scale sets the replica count; min_replicas is policy and doesn't change.
    transition = [replicas_after == target]

    invariants_after = _replica_invariants(replicas_after, min_replicas)
    missing = [
        key for key, value in (("replicas", known_replicas), ("min_replicas", known_min)) if value is None
    ]

    started = time.perf_counter()

    consistency = z3.Solver()
    consistency.set("timeout", timeout_ms)
    consistency.add(*state_facts, *transition)
    consistent = consistency.check()
    if consistent != z3.sat:
        return _result(
            None,
            started,
            missing,
            error=f"facts and transition are inconsistent (z3: {consistent}); refusing to approve",
        )

    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(*state_facts, *transition)
    solver.add(z3.Not(z3.And(*invariants_after.values())))
    answer = solver.check()

    pre_state_violations: list[str] = []
    if known_replicas is not None and known_min is not None:
        before = _replica_invariants(z3.IntVal(known_replicas), z3.IntVal(known_min))
        pre_state_violations = [name for name, expr in before.items() if z3.is_false(z3.simplify(expr))]

    if answer == z3.sat:
        model = solver.model()
        violated = [
            name
            for name, expr in invariants_after.items()
            if z3.is_false(model.eval(expr, model_completion=True))
        ]
        counterexample = {
            "before": {
                "replicas": model.eval(replicas_before, model_completion=True).as_long(),
                "min_replicas": model.eval(min_replicas, model_completion=True).as_long(),
            },
            "after": {"replicas": model.eval(replicas_after, model_completion=True).as_long()},
            "missing_facts_chosen_by_solver": missing,
        }
        return _result("sat", started, missing, violated, counterexample, pre_state_violations)

    return _result(str(answer), started, missing, pre_state_violations=pre_state_violations)


def _result(
    z3_result: str | None,
    started: float,
    missing: list[str],
    violated: list[str] | None = None,
    counterexample: dict[str, Any] | None = None,
    pre_state_violations: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "z3_result": z3_result,
        "violated_invariants": violated or [],
        "counterexample": counterexample,
        "pre_state_violations": pre_state_violations or [],
        "missing_facts": missing,
        "solver_ms": (time.perf_counter() - started) * 1000.0,
        "error": error,
    }
