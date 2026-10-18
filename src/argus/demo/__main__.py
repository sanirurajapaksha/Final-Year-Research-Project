"""End-to-end demo: one incident through the whole agent.

    python -m argus.demo [--save run.json]

    M4 compresses the telemetry -> M1 builds the context -> M2 (SIMULATED for now) proposes
    actions -> M4 sends every write to M3 -> M3 checks it, with cluster facts from saved kubectl
    output -> M4 runs what is approved (a stub: nothing really runs) -> M3's BLOCK verdicts go
    back to M2, whose next proposal is checked the same way.

Round 2's patch is read by M3's LLM Formulation Agent, so it needs ARGUS_LLM_API_KEY; without
a key M3 blocks it (fail-closed).
"""

import argparse
import json
from dataclasses import replace
from functools import partial
from pathlib import Path

from argus.config import Settings, load_settings
from argus.contracts import DiagnosisResult, ExecutionResult, SafetyVerdict, TelemetryBatch
from argus.demo.scenario import simulated_diagnose
from argus.orchestration.execution import handle_action
from argus.orchestration.pipeline import run_once
from argus.safety.gate import check

REPO = Path(__file__).resolve().parents[3]
TELEMETRY = REPO / "data" / "fixtures" / "m1" / "scenario_01" / "telemetry.json"
KUBECTL_OUTPUT = REPO / "data" / "fixtures" / "m3" / "kubectl"
DEMO_MODEL = "google/gemini-2.5-flash-lite"  # development and demo model (decided 17/10)


def demo_settings() -> Settings:
    """The user's settings, with the demo's defaults where nothing is set."""
    settings = load_settings()
    if not settings.m3_kubectl_output:
        settings = replace(settings, m3_kubectl_output=str(KUBECTL_OUTPUT))
    if not settings.llm_model:
        settings = replace(settings, llm_model=DEMO_MODEL)
    return settings


def run_demo(settings: Settings) -> dict:
    """Run the incident and return everything that happened, as plain JSON-ready data."""
    batch = TelemetryBatch.model_validate_json(TELEMETRY.read_text(encoding="utf-8"))
    gate = partial(check, settings=settings)

    # Round 1: the whole pipeline (M4 -> M1 -> M2 -> M4 -> M3 -> M4).
    result = run_once(batch, gate=gate, diagnoser=simulated_diagnose)
    rounds = [_round("M2 (SIMULATED) proposes", result.diagnosis, result.verdicts, result.executions)]

    # Round 2: run_once keeps M2's answer to the feedback without running it. The demo sends
    # those actions through M4 and M3 the same way, as the next round would.
    if result.feedback_diagnosis is not None:
        verdicts = []
        executions = []
        for action in result.feedback_diagnosis.actions:
            handled = handle_action(action, gate=gate)
            if handled.verdict is not None:
                verdicts.append(handled.verdict)
            if handled.execution is not None:
                executions.append(handled.execution)
        rounds.append(
            _round("M2 (SIMULATED) answers M3's feedback", result.feedback_diagnosis, verdicts, executions)
        )

    return {
        "incident": "cart is missing CART_ADDR (M1 scenario_01, synthetic, after Stratus's example)",
        "telemetry_records": len(batch.records),
        "context": {
            "notes": result.context.notes,
            "failing_services": result.context.failing_services,
            "anomalies": result.context.anomalies,
        },
        "rounds": rounds,
    }


def _round(
    title: str, diagnosis: DiagnosisResult, verdicts: list[SafetyVerdict], executions: list[ExecutionResult]
) -> dict:
    """One round: M2's hypotheses, and for each proposed action M3's verdict and M4's result."""
    actions = []
    for action in diagnosis.actions:
        entry = {"command": action.command, "is_write": action.is_write, "verdict": None, "execution": None}
        for verdict in verdicts:
            if verdict.command == action.command:
                entry["verdict"] = verdict.model_dump(mode="json")
        for execution in executions:
            if execution.command == action.command:
                entry["execution"] = execution.model_dump(mode="json")
        actions.append(entry)

    hypotheses = []
    for hypothesis in diagnosis.hypotheses:
        hypotheses.append(hypothesis.model_dump(mode="json"))
    return {"title": title, "hypotheses": hypotheses, "actions": actions}


def print_record(record: dict) -> None:
    print(f"Incident: {record['incident']}")
    print(f"M4  telemetry: {record['telemetry_records']} records, compressed and passed to M1")
    print(f"M1  context: {record['context']['notes']}")
    for anomaly in record["context"]["anomalies"]:
        print(f"    anomaly: {anomaly}")
    for number, one_round in enumerate(record["rounds"], start=1):
        print(f"\n--- Round {number}: {one_round['title']}")
        for hypothesis in one_round["hypotheses"]:
            print(f"  hypothesis {hypothesis['probability']:.2f}  {hypothesis['root_cause']}")
        for action in one_round["actions"]:
            _print_action(action)


def _print_action(action: dict) -> None:
    kind = "write" if action["is_write"] else "read"
    print(f"  {kind:<5}  {action['command']}")
    verdict = action["verdict"]
    if verdict is not None:
        print(f"         M3: {verdict['decision']} (z3: {verdict['z3_result']})  {verdict['reason']}")
        if verdict["counterexample"] is not None:
            print(f"         counterexample: {json.dumps(verdict['counterexample'])}")
        stages = []
        for stage, ms in verdict["timings_ms"].items():
            stages.append(f"{stage} {ms:.1f}")
        print(f"         timings (ms): {', '.join(stages)}")
        if "ARGUS_LLM_API_KEY" in verdict["reason"]:
            print("         (set ARGUS_LLM_API_KEY so M3's LLM can read this patch)")
    execution = action["execution"]
    if execution is not None:
        print(
            f"         M4: {'executed' if execution['executed'] else 'not executed'} ({execution['output']})"
        )


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(prog="python -m argus.demo", description="Run one incident end to end.")
    cli.add_argument("--save", type=Path, help="also write the whole run to this JSON file")
    args = cli.parse_args(argv)

    record = run_demo(demo_settings())
    print_record(record)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(record, indent=1), encoding="utf-8")
        print(f"\nRun saved to {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
