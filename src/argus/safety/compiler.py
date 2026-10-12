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

F1 slice:
    scale deployment          -> I1 minimum replicas (with the int32 range), I2 protected namespaces
    delete pod / namespace    -> I2 protected namespaces
    delete pvc                -> I2 protected namespaces, I4 in-use PVC
The gate blocks deletes of unprotected namespaces before they reach this module (fail-closed),
because deleting a namespace deletes everything in it, which F1 doesn't model.
"""

import time
from typing import Any

import z3

from argus.safety.policy import PROTECTED_NAMESPACES

INT32_MAX = 2**31 - 1
DELETABLE_KINDS = ("pod", "pvc", "namespace")


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
    if action.get("verb") == "delete" and action.get("kind") in DELETABLE_KINDS:
        return _solve_delete(action, facts, timeout_ms)
    raise EncodingError(f"no encoding for {action.get('verb')!r} on {action.get('kind')!r}")


def _in_protected_namespace(action: dict[str, Any]) -> bool:
    """Fact for I2: does the command touch a protected namespace?"""
    if action.get("params", {}).get("all_namespaces"):
        return True  # "all namespaces" includes the protected ones
    return action.get("namespace") in PROTECTED_NAMESPACES


def _fact(facts: dict[str, Any], key: str) -> int | None:
    value = facts.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise EncodingError(f"fact {key!r} must be an integer, got {value!r}")
    if not 0 <= value <= INT32_MAX:
        raise EncodingError(f"fact {key!r} is outside the Kubernetes int32 range: {value}")
    return value


def _bool_fact(facts: dict[str, Any], key: str) -> bool | None:
    value = facts.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise EncodingError(f"fact {key!r} must be true or false, got {value!r}")
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
    in_protected = z3.Bool("in_protected_namespace")
    state_facts.append(in_protected == _in_protected_namespace(action))

    # T(S0, A, S1): scale sets the replica count; min_replicas is policy and doesn't change.
    transition = [replicas_after == target]

    invariants_after = _replica_invariants(replicas_after, min_replicas)
    # I2: in a protected namespace the deployment must stay as it was.
    invariants_after["protected_namespace"] = z3.Implies(in_protected, replicas_after == replicas_before)
    checked = list(invariants_after)
    missing = [
        key for key, value in (("replicas", known_replicas), ("min_replicas", known_min)) if value is None
    ]

    started = time.perf_counter()
    answer, model, error = _check(state_facts, transition, invariants_after, timeout_ms)
    if error:
        return _result(None, started, missing, checked, error=error)

    pre_state_violations: list[str] = []
    if known_replicas is not None and known_min is not None:
        before = _replica_invariants(z3.IntVal(known_replicas), z3.IntVal(known_min))
        pre_state_violations = [name for name, expr in before.items() if z3.is_false(z3.simplify(expr))]

    if answer == z3.sat:
        counterexample = {
            "before": {
                "replicas": model.eval(replicas_before, model_completion=True).as_long(),
                "min_replicas": model.eval(min_replicas, model_completion=True).as_long(),
            },
            "after": {"replicas": model.eval(replicas_after, model_completion=True).as_long()},
            "missing_facts_chosen_by_solver": missing,
        }
        violated = _violated(model, invariants_after)
        return _result("sat", started, missing, checked, violated, counterexample, pre_state_violations)

    return _result(str(answer), started, missing, checked, pre_state_violations=pre_state_violations)


def _solve_delete(action: dict[str, Any], facts: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
    """Delete of a pod, PVC or (protected) namespace. The state is just "does the target exist"."""
    is_pvc = action["kind"] == "pvc"
    protected = _in_protected_namespace(action)

    exists_before = z3.Bool("exists_before")
    exists_after = z3.Bool("exists_after")
    in_protected = z3.Bool("in_protected_namespace")
    in_use = z3.Bool("in_use")

    # Facts(S0): the target exists; whether its namespace is protected; for a PVC, whether a pod uses it.
    state_facts = [exists_before, in_protected == protected]
    missing = []
    if is_pvc:
        known_in_use = _bool_fact(facts, "in_use")
        if known_in_use is None:
            missing.append("in_use")  # left unconstrained, so Z3 may pick True (fail-safe)
        else:
            state_facts.append(in_use == known_in_use)

    # T(S0, A, S1): delete removes the target.
    transition = [z3.Not(exists_after)]

    # I2: an object in a protected namespace is unchanged. I4: a PVC that a pod uses still exists.
    invariants_after = {"protected_namespace": z3.Implies(in_protected, exists_after == exists_before)}
    if is_pvc:
        invariants_after["pvc_in_use"] = z3.Implies(in_use, exists_after)
    checked = list(invariants_after)

    started = time.perf_counter()
    answer, model, error = _check(state_facts, transition, invariants_after, timeout_ms)
    if error:
        return _result(None, started, missing, checked, error=error)

    if answer == z3.sat:
        before = {"exists": True, "in_protected_namespace": protected}
        if is_pvc:
            before["in_use"] = z3.is_true(model.eval(in_use, model_completion=True))
        counterexample = {
            "before": before,
            "after": {"exists": False},
            "missing_facts_chosen_by_solver": missing,
        }
        violated = _violated(model, invariants_after)
        return _result("sat", started, missing, checked, violated, counterexample)

    return _result(str(answer), started, missing, checked)


def _check(
    state_facts: list, transition: list, invariants_after: dict[str, z3.BoolRef], timeout_ms: int
) -> tuple[z3.CheckSatResult | None, z3.ModelRef | None, str | None]:
    """Run the two Z3 checks. Returns (answer, model if sat, error)."""
    # 1. Facts and T must be consistent; otherwise check 2 would be unsat for no real reason.
    consistency = z3.Solver()
    consistency.set("timeout", timeout_ms)
    consistency.add(*state_facts, *transition)
    consistent = consistency.check()
    if consistent != z3.sat:
        return None, None, f"facts and transition are inconsistent (z3: {consistent}); refusing to approve"

    # 2. The negated safety property: Facts and T and not I.
    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(*state_facts, *transition)
    solver.add(z3.Not(z3.And(*invariants_after.values())))
    answer = solver.check()
    if answer == z3.sat:
        return answer, solver.model(), None
    return answer, None, None


def _violated(model: z3.ModelRef, invariants_after: dict[str, z3.BoolRef]) -> list[str]:
    """Names of the invariants that are false in the counterexample."""
    violated = []
    for name, expr in invariants_after.items():
        if z3.is_false(model.eval(expr, model_completion=True)):
            violated.append(name)
    return violated


def _result(
    z3_result: str | None,
    started: float,
    missing: list[str],
    checked: list[str],
    violated: list[str] | None = None,
    counterexample: dict[str, Any] | None = None,
    pre_state_violations: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "z3_result": z3_result,
        "checked_invariants": checked,
        "violated_invariants": violated or [],
        "counterexample": counterexample,
        "pre_state_violations": pre_state_violations or [],
        "missing_facts": missing,
        "solver_ms": (time.perf_counter() - started) * 1000.0,
        "error": error,
    }
