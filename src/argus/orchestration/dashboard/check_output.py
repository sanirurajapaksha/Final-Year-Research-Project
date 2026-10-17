"""Run with python -m argus.orchestration.dashboard.check_output [fixture.json]."""

import argparse
import json
from pathlib import Path

from argus.contracts import TelemetryBatch
from argus.orchestration.dashboard.measurements import DEFAULT_FIXTURE, measure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    try:
        output = measure(TelemetryBatch.model_validate_json(args.fixture.read_bytes()))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Invalid telemetry: {error}\n")
    print(json.dumps({key: value for key, value in output.items() if key != "tsv"}, indent=2))
    return int(not all(output["checks"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
