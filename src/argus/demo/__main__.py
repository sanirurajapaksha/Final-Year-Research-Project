"""End-to-end demo on the command line: one incident through the whole agent, stage by stage.

    python -m argus.demo [--scenario 1|2|3 | --telemetry FILE] [--save run.json]

The run is in flow.py. The Streamlit page (app.py) draws the same stages.
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from argus.demo.flow import SCENARIOS, load_telemetry, outcome, run_flow
from argus.demo.run import demo_settings


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(prog="python -m argus.demo", description="Run one incident end to end.")
    cli.add_argument("--scenario", type=int, default=1, help="sample incident: 1, 2 or 3 (default 1)")
    cli.add_argument("--telemetry", type=Path, help="a telemetry batch file instead of a sample")
    cli.add_argument("--save", type=Path, help="also write every stage to this JSON file")
    args = cli.parse_args(argv)

    names = list(SCENARIOS)
    if args.telemetry:
        name = str(args.telemetry)
        text = args.telemetry.read_text(encoding="utf-8")
    else:
        name = names[args.scenario - 1]
        text = SCENARIOS[name]["telemetry"].read_text(encoding="utf-8")

    print(f"Incident: {name}\n")
    stages = []
    for stage in run_flow(load_telemetry(text), demo_settings()):
        stages.append(stage)
        print(f"{stage['name']:<14} {stage['status']:<10} {stage['ms']:7.0f} ms  {stage['headline']}")

    result = outcome(stages)
    print(f"\n{result['title']}")
    if result["command"]:
        print(f"  {result['command']}")
    print(f"  {result['text']}")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(stages, indent=1, default=str), encoding="utf-8")
        print(f"\nRun saved to {args.save}")
    return 0


if __name__ == "__main__":
    # Settings and the LLM key from .env in the current folder; variables already set win.
    load_dotenv(".env")
    raise SystemExit(main())
