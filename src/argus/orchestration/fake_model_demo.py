"""Run a synthetic timeout/invalid-output fallback example with no API calls."""

import argparse
import json
import sys
from dataclasses import asdict

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from argus.orchestration.budget import EstimatedBudget
from argus.orchestration.fake_models import FakeStep, ScriptedAdapter
from argus.orchestration.model_dispatch import DispatchPolicy, DispatchResult, dispatch
from argus.orchestration.router import RoutingRequest


class DemoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: StrictStr = Field(min_length=1)


def run_demo(budget_units: int) -> DispatchResult:
    """Budget 17 funds both fallbacks; 15 stops the final fallback."""
    request = RoutingRequest(
        tasks=(
            {"task_id": "diagnose", "task_kind": "diagnostic_reasoning", "min_quality": 80},
            {"task_id": "parse", "task_kind": "telemetry_parsing", "min_quality": 70},
        ),
        candidates=(
            {
                "task_id": "diagnose",
                "model_id": "fake-frontier-a",
                "layer": "frontier",
                "estimated_cost_units": 4,
                "quality": 85,
            },
            {
                "task_id": "diagnose",
                "model_id": "fake-frontier-b",
                "layer": "frontier",
                "estimated_cost_units": 7,
                "quality": 98,
            },
            {
                "task_id": "parse",
                "model_id": "fake-low-a",
                "layer": "low_cost",
                "estimated_cost_units": 2,
                "quality": 75,
            },
            {
                "task_id": "parse",
                "model_id": "fake-low-b",
                "layer": "low_cost",
                "estimated_cost_units": 4,
                "quality": 90,
            },
        ),
        remaining_budget_units=budget_units,
        objective="min_cost",
        cost_unit="synthetic estimated credits, not currency",
        quality_source="hand-set fake scores, not measured accuracy",
    )
    policy = DispatchPolicy(
        max_attempts_per_task=2,
        timeout_ms=50,
        retry_on=("timeout", "error", "invalid_output"),
        fallbacks=(
            {"task_id": "diagnose", "model_ids": ("fake-frontier-b",)},
            {"task_id": "parse", "model_ids": ("fake-low-b",)},
        ),
    )
    adapter = ScriptedAdapter(
        {
            ("diagnose", "fake-frontier-a"): [FakeStep({"text": "late"}, elapsed_ms=51)],
            ("diagnose", "fake-frontier-b"): [FakeStep({"text": "synthetic diagnosis"}, elapsed_ms=10)],
            ("parse", "fake-low-a"): [FakeStep({"unexpected": "invalid schema"})],
            ("parse", "fake-low-b"): [FakeStep({"text": "synthetic parsed telemetry"}, elapsed_ms=5)],
        }
    )

    def validate(value: object) -> dict:
        return DemoOutput.model_validate(value).model_dump()

    return dispatch(
        request,
        adapter=adapter,
        prompts={"diagnose": "Diagnose this synthetic incident", "parse": "Parse this synthetic telemetry"},
        validators={"diagnose": validate, "parse": validate},
        policy=policy,
        budget=EstimatedBudget(budget_units, request.cost_unit),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=17, help="synthetic estimated credits; default 17")
    args = parser.parse_args(argv)
    try:
        result = run_demo(args.budget)
    except (ValueError, ValidationError) as error:
        print(f"fake model demo: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "mode": "scripted fake adapter; simulated deadlines; estimated accounting only",
                "plan": result.plan.model_dump(mode="json"),
                "tasks": [asdict(task) for task in result.tasks],
                "attempts": [asdict(attempt) for attempt in result.attempts],
                "budget": asdict(result.budget),
            },
            indent=2,
        )
    )
    return (
        0
        if result.plan.status == "optimal" and all(task.status == "succeeded" for task in result.tasks)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
