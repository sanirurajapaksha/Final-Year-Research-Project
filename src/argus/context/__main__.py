"""M1 Function 1 demo: telemetry fixture -> ingestion -> Stage 1 filter -> anomaly set.

python -m argus.context [path/to/telemetry.json]
"""

import json
import sys
from pathlib import Path

from argus.context.filters import extract_anomalies
from argus.context.ingest import IngestError, parse_records
from argus.contracts import TelemetryBatch

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[3] / "data" / "fixtures" / "m1" / "scenario_01" / "telemetry.json"
)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else DEFAULT_FIXTURE
    try:
        batch = TelemetryBatch.model_validate_json(path.read_text(encoding="utf-8"))
        telemetry = parse_records(batch.records)
    except (OSError, ValueError) as error:
        # IngestError and pydantic's ValidationError are both ValueErrors.
        kind = "invalid telemetry" if isinstance(error, IngestError) else "can't read fixture"
        print(f"error: {kind}: {error}", file=sys.stderr)
        return 1

    anomalies = extract_anomalies(telemetry)

    print(json.dumps([signal.model_dump(mode="json") for signal in anomalies], indent=2))
    print(
        f"{len(anomalies)} anomalies from {telemetry.total} records "
        f"({len(telemetry.metrics)} metrics, {len(telemetry.logs)} logs, "
        f"{len(telemetry.spans)} spans, {len(telemetry.k8s)} k8s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
