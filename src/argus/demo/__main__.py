"""End-to-end demo on the command line: one incident through the whole agent.

    python -m argus.demo [--save run.json]

What runs is described in run.py. The Streamlit page (app.py) shows the same run.
"""

import argparse
import json
from pathlib import Path

from argus.demo.run import demo_settings, run_demo, verdict_line


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
        print(f"         {verdict_line(verdict)}  {verdict['reason']}")
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
        status = "not executed"
        if execution["executed"]:
            status = "executed"
        print(f"         M4: {status} ({execution['output']})")


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
