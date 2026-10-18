"""Offline W3-05 binary linear router; no provider calls or cluster execution.

TAF task/layer eligibility is fixed. Objective, estimates and budget are explicit
inputs. Quality scores are supplied estimates, not measured SRE accuracy.
"""

from collections import defaultdict
from typing import Annotated, Literal, Self

import z3
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
Quality = Annotated[StrictInt, Field(ge=0, le=100)]
Cost = Annotated[StrictInt, Field(ge=0)]
TaskKind = Literal["telemetry_parsing", "diagnostic_reasoning"]
Layer = Literal["low_cost", "frontier"]
Objective = Literal["max_quality", "min_cost"]
REQUIRED_LAYER: dict[TaskKind, Layer] = {
    "telemetry_parsing": "low_cost",
    "diagnostic_reasoning": "frontier",
}


class RoutingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class RoutingTask(RoutingModel):
    task_id: Identifier
    task_kind: TaskKind
    min_quality: Quality


class CandidateEstimate(RoutingModel):
    task_id: Identifier
    model_id: Identifier
    layer: Layer
    estimated_cost_units: Cost
    quality: Quality


class RoutingRequest(RoutingModel):
    tasks: tuple[RoutingTask, ...]
    candidates: tuple[CandidateEstimate, ...]
    remaining_budget_units: Cost
    objective: Objective
    cost_unit: Identifier
    quality_source: Identifier

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        task_ids = {task.task_id for task in self.tasks}
        if len(task_ids) != len(self.tasks):
            raise ValueError("duplicate task_id")
        pairs: set[tuple[str, str]] = set()
        layers: dict[str, Layer] = {}
        for candidate in self.candidates:
            if candidate.task_id not in task_ids:
                raise ValueError(f"unknown task_id: {candidate.task_id}")
            pair = (candidate.task_id, candidate.model_id)
            if pair in pairs:
                raise ValueError(f"duplicate task/model pair: {pair}")
            pairs.add(pair)
            if candidate.model_id in layers and layers[candidate.model_id] != candidate.layer:
                raise ValueError(f"inconsistent layer for model: {candidate.model_id}")
            layers[candidate.model_id] = candidate.layer
        return self


class RoutingPlan(RoutingModel):
    status: Literal["optimal", "infeasible", "solver_error"]
    assignments: tuple[CandidateEstimate, ...] = ()
    total_estimated_cost_units: Cost = 0
    total_estimated_quality: Annotated[StrictInt, Field(ge=0)] = 0
    reason: str = ""


def route(request: RoutingRequest, *, timeout_ms: int = 5000) -> RoutingPlan:
    """Return a complete optimal assignment or an empty failure plan.

    max_quality: maximize total quality, then minimize cost.
    min_cost: minimize total cost, then maximize quality.
    Both use model-ID order per sorted task ID to resolve remaining ties.
    timeout_ms bounds solver checking, not the entire Python call.
    """
    request = RoutingRequest.model_validate(request)
    if type(timeout_ms) is not int or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    if not request.tasks:
        return RoutingPlan(status="optimal")

    by_task: dict[str, list[CandidateEstimate]] = defaultdict(list)
    tasks = {task.task_id: task for task in request.tasks}
    for candidate in request.candidates:
        task = tasks[candidate.task_id]
        if candidate.layer == REQUIRED_LAYER[task.task_kind] and candidate.quality >= task.min_quality:
            by_task[task.task_id].append(candidate)
    for task_id in sorted(tasks):
        if not by_task[task_id]:
            return RoutingPlan(status="infeasible", reason=f"no eligible candidate for {task_id}")

    try:
        # Isolate solver symbols/contexts across separate routing calls.
        context = z3.Context()
        solver = z3.Optimize(ctx=context)
        solver.set(timeout=timeout_ms, priority="lex")
        options: list[tuple[CandidateEstimate, z3.BoolRef]] = []
        tie_expressions = []
        for task_index, task_id in enumerate(sorted(tasks)):
            candidates = sorted(by_task[task_id], key=lambda candidate: candidate.model_id)
            choices = [z3.Bool(f"task_{task_index}_model_{i}", ctx=context) for i in range(len(candidates))]
            solver.add(z3.Sum([z3.If(choice, 1, 0) for choice in choices]) == 1)
            options.extend(zip(candidates, choices, strict=True))
            tie_expressions.append(z3.Sum([z3.If(choice, i, 0) for i, choice in enumerate(choices)]))

        cost = z3.Sum([z3.If(choice, candidate.estimated_cost_units, 0) for candidate, choice in options])
        quality = z3.Sum([z3.If(choice, candidate.quality, 0) for candidate, choice in options])
        solver.add(cost <= request.remaining_budget_units)
        if request.objective == "max_quality":
            objectives = [solver.maximize(quality), solver.minimize(cost)]
        else:
            objectives = [solver.minimize(cost), solver.maximize(quality)]
        objectives.extend(solver.minimize(expression) for expression in tie_expressions)

        status = solver.check()
        if status == z3.unsat:
            return RoutingPlan(status="infeasible", reason="no complete assignment fits the shared budget")
        if status != z3.sat:
            return RoutingPlan(
                status="solver_error", reason=f"solver did not finish: {solver.reason_unknown()}"
            )
        # Do not return a feasible incumbent as an optimum after an interrupted solve.
        if any(objective.lower().as_long() != objective.upper().as_long() for objective in objectives):
            return RoutingPlan(status="solver_error", reason="solver did not prove all objectives optimal")

        model = solver.model()
        selected = tuple(candidate for candidate, choice in options if z3.is_true(model.eval(choice)))
        return RoutingPlan(
            status="optimal",
            assignments=selected,
            total_estimated_cost_units=sum(candidate.estimated_cost_units for candidate in selected),
            total_estimated_quality=sum(candidate.quality for candidate in selected),
        )
    except z3.Z3Exception as error:
        return RoutingPlan(status="solver_error", reason=f"Z3 error: {error}")
