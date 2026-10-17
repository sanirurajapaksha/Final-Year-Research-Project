"""Shared live measurements for the terminal and browser demo."""

import json
from pathlib import Path

from argus.context.ingest import decode_tsv, parse_records
from argus.contracts import TelemetryBatch
from argus.orchestration.service import compress

DEFAULT_FIXTURE = Path(__file__).resolve().parents[4] / "data/fixtures/m1/scenario_01/telemetry.json"


def measure(batch: TelemetryBatch) -> dict:
    """Measure actual UTF-8 payloads; validate exact JSON values and types."""
    parse_records(batch.records)
    before = batch.model_copy(deep=True)
    default = json.dumps(batch.records, ensure_ascii=False).encode("utf-8")
    compact = json.dumps(batch.records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    result = compress(batch)
    payload = result.content.encode("utf-8")
    restored = decode_tsv(result.content)

    def canonical(records):
        return json.dumps(records, ensure_ascii=False, sort_keys=True, allow_nan=False)

    def reduction(size):
        return 100 * (size - len(payload)) / size if size else None

    return {
        "records": len(batch.records),
        "default_json_bytes": len(default),
        "compact_json_bytes": len(compact),
        "tsv_bytes": len(payload),
        "reduction_vs_default": reduction(len(default)),
        "reduction_vs_compact": reduction(len(compact)),
        "checks": {
            "Exact round-trip values, types and order": canonical(restored) == canonical(before.records),
            "Alert time preserved": result.alert_time == before.alert_time,
            "Input batch unchanged": batch == before,
            "Compressor byte counts match": (
                result.original_size == len(default) and result.compressed_size == len(payload)
            ),
        },
        "tsv": result.content,
    }
