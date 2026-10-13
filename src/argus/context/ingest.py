"""F1 ingestion: turn telemetry records into typed models.

Two entry routes, both ending in `parse_records`:
- M4's compressed TSV (`decode_tsv`), the format described in docs/functions/m4/F1.md.
- `TelemetryBatch.records` directly, for fixtures and evaluation without M4.
"""

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError

from argus.contracts import K8sEntity, LogRecord, MetricSample, Span, TelemetryRecord

_record_adapter = TypeAdapter(TelemetryRecord)


class IngestError(ValueError):
    """Telemetry that M1 can't read. Raised instead of silently dropping records."""


@dataclass
class ParsedTelemetry:
    """Typed telemetry, grouped by record type."""

    metrics: list[MetricSample] = field(default_factory=list)
    logs: list[LogRecord] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    k8s: list[K8sEntity] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.metrics) + len(self.logs) + len(self.spans) + len(self.k8s)


def decode_tsv(content: str) -> list[dict[str, Any]]:
    """Decode M4's TSV back to the original record dicts.

    The first row is the header. Every present cell is JSON; an empty cell means the field
    was missing from the record, so it is left out of the dict.
    """
    if not content:
        return []
    rows = csv.reader(io.StringIO(content, newline=""), delimiter="\t")
    header = next(rows)
    records = []
    for number, row in enumerate(rows, start=2):
        if len(row) != len(header):
            raise IngestError(f"TSV row {number} has {len(row)} cells, header has {len(header)}")
        cells = zip(header, row, strict=True)
        try:
            records.append({key: json.loads(cell) for key, cell in cells if cell != ""})
        except json.JSONDecodeError as error:
            raise IngestError(f"TSV row {number} has a cell that isn't JSON: {error}") from error
    return records


def parse_records(records: list[dict[str, Any]]) -> ParsedTelemetry:
    """Validate each record against its contract model, chosen by its `kind`."""
    parsed = ParsedTelemetry()
    groups = {
        MetricSample: parsed.metrics,
        LogRecord: parsed.logs,
        Span: parsed.spans,
        K8sEntity: parsed.k8s,
    }
    for index, record in enumerate(records):
        try:
            typed = _record_adapter.validate_python(record)
        except ValidationError as error:
            raise IngestError(f"record {index} is not valid telemetry: {error}") from error
        groups[type(typed)].append(typed)
    return parsed
