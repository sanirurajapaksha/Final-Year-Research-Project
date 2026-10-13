"""M4 entry points: telemetry preprocessing and the execution handler.

compress() converts JSON records to TSV. execute() remains a stub.
Compression preserves contract v1 records and the batch alert time.
"""

import csv
import io
import json

from argus.contracts import CompressedTelemetry, ExecutionResult, ProposedAction, TelemetryBatch


def compress(batch: TelemetryBatch) -> CompressedTelemetry:
    """Convert JSON records to TSV, keeping every present value as JSON."""
    original = json.dumps(batch.records, ensure_ascii=False)
    columns = list(dict.fromkeys(key for record in batch.records for key in record))
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t")
    if batch.records:
        writer.writerow(columns)
        for record in batch.records:
            writer.writerow(
                [json.dumps(record[key], ensure_ascii=False) if key in record else "" for key in columns]
            )
    content = output.getvalue()
    return CompressedTelemetry(
        content=content,
        alert_time=batch.alert_time,
        original_size=len(original.encode("utf-8")),
        compressed_size=len(content.encode("utf-8")),
    )


def execute(action: ProposedAction) -> ExecutionResult:
    """Run a command on the cluster.

    Only call this for read actions, or for write actions that M3 approved.
    The stub never runs anything, so the boilerplate can't touch a real cluster.
    """
    return ExecutionResult(
        command=action.command,
        executed=False,
        output="stub: execution handler not implemented yet (nothing was run)",
    )
