"""Demo: one pass of the (stub) pipeline on a telemetry fixture.

python -m sre_agent [path/to/telemetry.json]
"""

import sys
from pathlib import Path

from sre_agent.contracts import TelemetryBatch
from sre_agent.orchestration.pipeline import run_once

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "telemetry_sample.json"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else DEFAULT_FIXTURE
    batch = TelemetryBatch.model_validate_json(path.read_text(encoding="utf-8"))

    result = run_once(batch)

    print(f"Context: {result.context.notes or result.context.anomalies}")
    for hypothesis in result.diagnosis.hypotheses:
        print(f"Hypothesis: {hypothesis.root_cause} (p={hypothesis.probability:.2f})")
    for verdict in result.verdicts:
        print(f"M3 {verdict.decision}: {verdict.command!r} ({verdict.reason})")
    for execution in result.executions:
        status = "executed" if execution.executed else "not executed"
        print(f"M4 {status}: {execution.command!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
