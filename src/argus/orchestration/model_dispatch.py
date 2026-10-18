"""Provider-independent sequential dispatch with explicit fallback policy.

The supplied adapter owns deadline enforcement. This prototype supplies and tests
a scripted adapter; it does not implement transport cancellation or real billing.
Model outputs are validated data and are never executed as cluster commands here.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, StrictInt, model_validator

from argus.orchestration.budget import BudgetExceeded, BudgetSnapshot, EstimatedBudget
from argus.orchestration.router import (
    REQUIRED_LAYER,
    CandidateEstimate,
    Identifier,
    RoutingModel,
    RoutingPlan,
    RoutingRequest,
    RoutingTask,
    route,
)

FailureKind = Literal["timeout", "error", "invalid_output"]


class FallbackRule(RoutingModel):
    task_id: Identifier
    # Repeating a model explicitly requests another attempt on that model.
    model_ids: tuple[Identifier, ...]


class DispatchPolicy(RoutingModel):
    """Cap attempts at the initial call plus explicitly listed fallbacks.

    max_attempts_per_task does not create retries. To retry the same model,
    repeat its ID in the task's fallback rule.
    """

    max_attempts_per_task: Annotated[StrictInt, Field(ge=1)]
    timeout_ms: Annotated[StrictInt, Field(gt=0)]
    retry_on: tuple[FailureKind, ...]
    fallbacks: tuple[FallbackRule, ...]
    solver_timeout_ms: Annotated[StrictInt, Field(gt=0)] = 5000

    @model_validator(mode="after")
    def unique_rules(self) -> Self:
        if len({rule.task_id for rule in self.fallbacks}) != len(self.fallbacks):
            raise ValueError("duplicate fallback task_id")
        if len(set(self.retry_on)) != len(self.retry_on):
            raise ValueError("duplicate retry condition")
        return self


@dataclass(frozen=True)
class AdapterReply:
    output: object
    elapsed_ms: int

    def __post_init__(self):
        if type(self.elapsed_ms) is not int or self.elapsed_ms < 0:
            raise ValueError("elapsed_ms must be a nonnegative integer")


class ModelAdapter(Protocol):
    def call(
        self, task: RoutingTask, candidate: CandidateEstimate, prompt: str, *, timeout_ms: int
    ) -> AdapterReply:
        """Honor the deadline or raise TimeoutError; never execute returned actions."""
        ...


@dataclass(frozen=True)
class Attempt:
    task_id: str
    model_id: str
    status: Literal["success", "timeout", "error", "invalid_output"]
    charged_estimated_units: int
    reason: str = ""


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    status: Literal["succeeded", "failed", "budget_exhausted"]
    output: object = None
    reason: str = ""


@dataclass(frozen=True)
class DispatchResult:
    plan: RoutingPlan
    tasks: tuple[TaskResult, ...]
    attempts: tuple[Attempt, ...]
    budget: BudgetSnapshot


def dispatch(
    request: RoutingRequest,
    *,
    adapter: ModelAdapter,
    prompts: Mapping[str, str],
    validators: Mapping[str, Callable[[object], object]],
    policy: DispatchPolicy,
    budget: EstimatedBudget,
) -> DispatchResult:
    """Plan once, reserve all initial calls, then dispatch in task-ID order.

    Fallbacks follow caller-supplied order, remain in the eligible TAF layer and
    meet minimum quality. They may use only unreserved budget. Validators must
    return a validated value or raise; no default output schema is invented.
    The request must match the ledger's available balance and cost units.
    """
    request = RoutingRequest.model_validate(request)
    policy = DispatchPolicy.model_validate(policy)
    if not callable(getattr(adapter, "call", None)):
        raise ValueError("adapter must provide a callable call method")
    tasks = {task.task_id: task for task in request.tasks}
    if set(prompts) != set(tasks) or any(not isinstance(prompt, str) for prompt in prompts.values()):
        raise ValueError("provide exactly one string prompt for every task")
    if set(validators) != set(tasks) or any(not callable(validator) for validator in validators.values()):
        raise ValueError("provide exactly one output validator for every task")
    balance = budget.snapshot()
    if request.cost_unit != balance.cost_unit or request.remaining_budget_units != balance.available_units:
        raise ValueError("request budget and units must match the ledger's available balance")

    candidates = {(candidate.task_id, candidate.model_id): candidate for candidate in request.candidates}
    fallback_candidates: dict[str, tuple[CandidateEstimate, ...]] = {}
    for rule in policy.fallbacks:
        if rule.task_id not in tasks:
            raise ValueError(f"unknown fallback task: {rule.task_id}")
        task = tasks[rule.task_id]
        choices = []
        for model_id in rule.model_ids:
            candidate = candidates.get((task.task_id, model_id))
            if candidate is None:
                raise ValueError(f"unknown fallback candidate: {task.task_id}/{model_id}")
            if candidate.layer != REQUIRED_LAYER[task.task_kind] or candidate.quality < task.min_quality:
                raise ValueError(f"ineligible fallback candidate: {task.task_id}/{model_id}")
            choices.append(candidate)
        fallback_candidates[task.task_id] = tuple(choices)

    plan = route(request, timeout_ms=policy.solver_timeout_ms)
    if plan.status != "optimal":
        return DispatchResult(plan, (), (), budget.snapshot())

    reservations: dict[str, object] = {}
    results = []
    attempts = []
    try:
        for candidate in plan.assignments:
            reservations[candidate.task_id] = budget.reserve(candidate.estimated_cost_units)
        for initial in plan.assignments:
            task = tasks[initial.task_id]
            choices = (initial, *fallback_candidates.get(task.task_id, ()))[: policy.max_attempts_per_task]
            task_result = TaskResult(task.task_id, "failed", reason="no successful attempt")
            for index, candidate in enumerate(choices):
                if index == 0:
                    token = reservations.pop(task.task_id)
                else:
                    try:
                        token = budget.reserve(candidate.estimated_cost_units)
                    except BudgetExceeded:
                        task_result = TaskResult(
                            task.task_id, "budget_exhausted", reason="fallback cannot fit unreserved budget"
                        )
                        break
                # Conservative estimated charging: even timeout/error/invalid output consumes the estimate.
                budget.charge(token)
                output = None
                try:
                    reply = adapter.call(task, candidate, prompts[task.task_id], timeout_ms=policy.timeout_ms)
                    if not isinstance(reply, AdapterReply):
                        status, reason = "invalid_output", "adapter returned no AdapterReply"
                    elif reply.elapsed_ms > policy.timeout_ms:
                        status, reason = "timeout", "adapter reported completion after the deadline"
                    else:
                        try:
                            output = validators[task.task_id](reply.output)
                            status, reason = "success", ""
                        except Exception as error:
                            status, reason = "invalid_output", f"{type(error).__name__}: {error}"
                except TimeoutError as error:
                    status, reason = "timeout", f"{type(error).__name__}: {error}"
                except Exception as error:
                    status, reason = "error", f"{type(error).__name__}: {error}"
                attempts.append(
                    Attempt(task.task_id, candidate.model_id, status, candidate.estimated_cost_units, reason)
                )
                if status == "success":
                    task_result = TaskResult(task.task_id, "succeeded", output=output)
                    break
                task_result = TaskResult(task.task_id, "failed", reason=reason)
                if status not in policy.retry_on:
                    break
            results.append(task_result)
    finally:
        # Includes cancellation/interrupt cleanup: unstarted calls retain no reservations.
        for token in reservations.values():
            budget.release(token)

    return DispatchResult(plan, tuple(results), tuple(attempts), budget.snapshot())
