"""M4 action handling: in-process M3 approval before dispatching a write."""

from collections.abc import Callable
from dataclasses import dataclass

from argus.contracts import ExecutionResult, GateDecision, ProposedAction, SafetyVerdict
from argus.orchestration.service import execute
from argus.safety.gate import check

Gate = Callable[[ProposedAction], SafetyVerdict]
Executor = Callable[[ProposedAction], ExecutionResult]


@dataclass
class ActionResult:
    verdict: SafetyVerdict | None = None
    execution: ExecutionResult | None = None


def handle_action(
    action: ProposedAction,
    *,
    gate: Gate | None = None,
    executor: Executor | None = None,
) -> ActionResult:
    """Dispatch reads and approved writes; gate failures block writes.

    The default gate blocks without cluster facts; a caller can supply an M3
    adapter configured with a recorded snapshot. The default executor is a
    labelled stub. Copies isolate the original proposal from adapter mutation.
    """
    executor = executor if executor is not None else execute
    if not action.is_write:
        return ActionResult(execution=executor(action.model_copy(deep=True)))

    gate = gate if gate is not None else check
    try:
        verdict = gate(action.model_copy(deep=True))
        if not isinstance(verdict, SafetyVerdict) or verdict.command != action.command:
            raise ValueError("gate returned no matching SafetyVerdict")
    except Exception as error:
        verdict = SafetyVerdict(
            command=action.command,
            decision=GateDecision.BLOCK,
            reason=f"M4 gate failure: {type(error).__name__}: {error} (fail-closed)",
        )

    result = ActionResult(verdict=verdict)
    if verdict.decision is GateDecision.APPROVE:
        result.execution = executor(action.model_copy(deep=True))
    return result
