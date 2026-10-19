"""Plain-data PP1 reports and a labelled offline replay of the saved diagnosis.

The replay runs the real router/dispatcher with scripted responses. It does not
represent model calls made by run_once and never handles or executes actions.
"""

import json
from dataclasses import asdict
from pathlib import Path

from argus.context.ingest import decode_tsv
from argus.contracts import DiagnosisResult, TelemetryBatch
from argus.orchestration.budget import EstimatedBudget
from argus.orchestration.fake_models import FakeStep, ScriptedAdapter
from argus.orchestration.model_dispatch import DispatchPolicy, dispatch
from argus.orchestration.router import RoutingRequest
from argus.orchestration.service import compress

SCENARIO = Path(__file__).resolve().parents[3] / "data/fixtures/m1/scenario_01/telemetry.json"
OUTCOMES = ("Success", "Timeout", "Invalid output", "Model error")


def load_scenario() -> TelemetryBatch:
    """Load the same synthetic scenario_01 input used by the shared demo."""
    return TelemetryBatch.model_validate_json(SCENARIO.read_text(encoding="utf-8"))


def build_report(batch: TelemetryBatch, record: dict) -> dict:
    """Measure compression again and summarize action handling from the saved run."""
    compressed = compress(batch)
    restored = decode_tsv(compressed.content)
    compact_size = len(json.dumps(batch.records, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    actions = []
    for one_round in record["rounds"]:
        for action in one_round["actions"]:
            verdict = action["verdict"]
            execution = action["execution"]
            actions.append(
                {
                    "round": one_round["title"],
                    "command": action["command"],
                    "kind": "write" if action["is_write"] else "read",
                    "M3": verdict["decision"] if verdict else "not asked",
                    "reason": verdict["reason"] if verdict else "",
                    "executor_reached": execution is not None,
                    "executed": execution["executed"] if execution else False,
                    "output": execution["output"] if execution else "",
                }
            )
    original = json.dumps(batch.records, ensure_ascii=False, sort_keys=True, allow_nan=False)
    decoded = json.dumps(restored, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return {
        "records": len(batch.records),
        "original_json_bytes": compressed.original_size,
        "compact_json_bytes": compact_size,
        "tsv_bytes": compressed.compressed_size,
        "reduction_percent": 100 * (1 - compressed.compressed_size / compressed.original_size),
        "round_trip_exact": original == decoded,
        "alert_time_preserved": compressed.alert_time == batch.alert_time,
        "tsv": compressed.content,
        "actions": actions,
    }


def routing_replay(record: dict, *, budget: int = 5, outcome: str = "Timeout") -> dict:
    """Replay the first saved diagnosis through scripted primary/fallback models.

    Costs and quality are invented estimates. Deadlines are simulated without
    sleeping. No providers, settings, .env files, gates or executors are invoked.
    """
    if outcome not in OUTCOMES:
        raise ValueError("unknown scripted outcome")
    first_round = record["rounds"][0]
    diagnosis = DiagnosisResult.model_validate(
        {"hypotheses": first_round["hypotheses"], "actions": first_round["actions"]}
    ).model_dump(mode="json")
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
        cost_unit="synthetic credits, not currency",
        quality_source="hand-set scores, not measured accuracy",
    )
    primary = {
        "Success": FakeStep(diagnosis),
        "Timeout": FakeStep(diagnosis, elapsed_ms=51),
        "Invalid output": FakeStep({"hypotheses": [{"probability": 2}]}),
        "Model error": FakeStep(error=RuntimeError("scripted provider error")),
    }[outcome]
    adapter = ScriptedAdapter(
        {("diagnose", "fake-primary"): [primary], ("diagnose", "fake-fallback"): [FakeStep(diagnosis)]}
    )
    policy = DispatchPolicy(
        max_attempts_per_task=2,
        timeout_ms=50,
        retry_on=("timeout", "error", "invalid_output"),
        fallbacks=[{"task_id": "diagnose", "model_ids": ["fake-fallback"]}],
    )
    result = dispatch(
        request,
        adapter=adapter,
        prompts={"diagnose": json.dumps({"context": record["context"]})},
        validators={"diagnose": lambda value: DiagnosisResult.model_validate(value, strict=True)},
        policy=policy,
        budget=EstimatedBudget(budget, request.cost_unit),
    )
    return {
        "mode": "Offline scripted replay of the saved diagnosis; no actions handled",
        "request": request.model_dump(mode="json"),
        "policy": policy.model_dump(mode="json"),
        "plan": result.plan.model_dump(mode="json"),
        "attempts": [asdict(attempt) for attempt in result.attempts],
        "budget": asdict(result.budget),
        "tasks": [
            {"task_id": task.task_id, "status": task.status, "reason": task.reason} for task in result.tasks
        ],
    }
