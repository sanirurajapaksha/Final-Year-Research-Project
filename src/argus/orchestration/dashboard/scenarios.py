"""Local F2 scenarios: synthetic estimates, scripted models and a no-op executor."""

import json
from dataclasses import asdict
from functools import partial
from pathlib import Path

from argus.config import Settings
from argus.contracts import DiagnosisResult, ExecutionResult, SemanticContext
from argus.orchestration.budget import EstimatedBudget
from argus.orchestration.fake_models import FakeStep, ScriptedAdapter
from argus.orchestration.function2 import run_function2
from argus.orchestration.model_dispatch import DispatchPolicy
from argus.orchestration.router import REQUIRED_LAYER, RoutingRequest, route
from argus.safety.gate import check

FIXTURES = Path(__file__).resolve().parents[4] / "data/fixtures"
FAILURES = ("Success", "Timeout", "Invalid output", "Model error")


def routing_demo(budget: int, quality: int, objective: str) -> dict:
    """Solve the existing two-task fixture with explicit interactive overrides."""
    payload = json.loads((FIXTURES / "m4/routing_synthetic.json").read_text(encoding="utf-8"))
    payload.update(remaining_budget_units=budget, objective=objective)
    for task in payload["tasks"]:
        task["min_quality"] = quality
    request = RoutingRequest.model_validate(payload)
    plan = route(request)
    tasks = {task.task_id: task for task in request.tasks}
    candidates = []
    for candidate in request.candidates:
        task = tasks[candidate.task_id]
        reason = (
            "Wrong layer"
            if candidate.layer != REQUIRED_LAYER[task.task_kind]
            else "Below minimum quality"
            if candidate.quality < task.min_quality
            else "Eligible"
        )
        candidates.append({**candidate.model_dump(), "eligibility": reason})
    return {
        "request": request.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "candidates": candidates,
    }


def safety_demo(budget: int, failure: str, replicas: int) -> dict:
    """Run the real Function 2 facade and M3 gate against a hand-written snapshot."""
    if failure not in FAILURES:
        raise ValueError("unknown scripted outcome")
    request = RoutingRequest(
        tasks=[{"task_id": "diagnose", "task_kind": "diagnostic_reasoning", "min_quality": 80}],
        candidates=[
            {
                "task_id": "diagnose",
                "model_id": model,
                "layer": "frontier",
                "estimated_cost_units": cost,
                "quality": quality,
            }
            for model, cost, quality in [("fake-primary", 2, 85), ("fake-fallback", 3, 90)]
        ],
        remaining_budget_units=budget,
        objective="min_cost",
        cost_unit="synthetic estimated credits, not currency",
        quality_source="hand-set scores, not measured accuracy",
    )
    context = SemanticContext(
        services=["geo", "frontend"],
        dependencies=[("frontend", "geo")],
        symptoms=["Synthetic HTTP 5xx"],
        failing_services=["geo"],
        notes="Independent scripted F2 example; not a diagnosis of the telemetry upload.",
    )
    diagnosis = {
        "hypotheses": [
            {
                "root_cause": "Scripted capacity example",
                "probability": 0.9,
                "evidence": ["Invented demo response; not RCA evidence"],
            }
        ],
        "actions": [
            {"command": "kubectl get pods -n hotel-reservation", "is_write": False},
            {
                "command": f"kubectl scale deployment geo --replicas={replicas} -n hotel-reservation",
                "is_write": True,
            },
        ],
    }
    primary = {
        "Success": FakeStep(diagnosis),
        "Timeout": FakeStep(diagnosis, elapsed_ms=51),
        "Invalid output": FakeStep({"hypotheses": [{"probability": 2}]}),
        "Model error": FakeStep(error=RuntimeError("scripted provider error")),
    }[failure]
    adapter = ScriptedAdapter(
        {("diagnose", "fake-primary"): [primary], ("diagnose", "fake-fallback"): [FakeStep(diagnosis)]}
    )
    policy = DispatchPolicy(
        max_attempts_per_task=2,
        timeout_ms=50,
        retry_on=("timeout", "error", "invalid_output"),
        fallbacks=[{"task_id": "diagnose", "model_ids": ["fake-fallback"]}],
    )
    snapshot = json.loads((FIXTURES / "m3/snapshot_hotel_reservation.json").read_text(encoding="utf-8"))
    feedback_received = []

    def feedback_handler(context, *, feedback):
        feedback_received.extend(verdict.model_dump(mode="json") for verdict in feedback)
        return DiagnosisResult(
            actions=[
                {
                    "command": "kubectl scale deployment geo --replicas=2 -n hotel-reservation",
                    "is_write": True,
                }
            ]
        )

    def stub_executor(action):
        return ExecutionResult(
            command=action.command, executed=False, output="Demo executor reached; no command was run."
        )

    result = run_function2(
        context,
        request=request,
        adapter=adapter,
        policy=policy,
        budget=EstimatedBudget(budget, request.cost_unit),
        gate=partial(check, snapshot=snapshot, settings=Settings(solver_timeout_s=5)),
        executor=stub_executor,
        feedback_handler=feedback_handler,
    )
    pipeline = result.pipeline
    return {
        "mode": "Scripted models; synthetic credits; hand-written snapshot; no-op executor",
        "request": request.model_dump(mode="json"),
        "policy": policy.model_dump(mode="json"),
        "context": context.model_dump(mode="json"),
        "snapshot": snapshot,
        "plan": result.dispatch.plan.model_dump(mode="json"),
        "attempts": [asdict(item) for item in result.dispatch.attempts],
        "tasks": [
            {"task_id": item.task_id, "status": item.status, "reason": item.reason}
            for item in result.dispatch.tasks
        ],
        "budget": asdict(result.dispatch.budget),
        "diagnosis": pipeline.diagnosis.model_dump(mode="json") if pipeline else None,
        "verdicts": [item.model_dump(mode="json") for item in pipeline.verdicts] if pipeline else [],
        "executions": [item.model_dump(mode="json") for item in pipeline.executions] if pipeline else [],
        "feedback_received": feedback_received,
        "feedback_diagnosis": pipeline.feedback_diagnosis.model_dump(mode="json")
        if pipeline and pipeline.feedback_diagnosis
        else None,
        "feedback_error": pipeline.feedback_error if pipeline else "",
    }
