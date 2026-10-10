"""M4 entry points: telemetry preprocessing and the execution handler.

STUB: replace the bodies. Keep the signatures until contract v1 changes them.
"""

from argus.contracts import CompressedTelemetry, ExecutionResult, ProposedAction, TelemetryBatch


def compress(batch: TelemetryBatch) -> CompressedTelemetry:
    """Preprocess and compress raw telemetry before M1 sees it.

    The stub passes the records through as one line each, uncompressed.
    """
    content = "\n".join(str(record) for record in batch.records)
    size = len(content.encode("utf-8"))
    return CompressedTelemetry(content=content, original_size=size, compressed_size=size)


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
