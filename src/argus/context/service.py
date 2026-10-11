"""M1 entry point.

F1 is wired in: M4's TSV -> typed records -> Stage 1 filter. F2 (service dependency graph and
Stage 2 pruning) is not built yet, so the context holds the Stage 1 anomaly set only.
"""

from argus.context.filters import Thresholds, extract_anomalies
from argus.context.ingest import IngestError, decode_tsv, parse_records
from argus.contracts import CompressedTelemetry, SemanticContext

STRATEGY = "stage1"


def build_context(telemetry: CompressedTelemetry, thresholds: Thresholds | None = None) -> SemanticContext:
    """Turn M4's compressed telemetry into the Semantic Context Object for M2.

    Telemetry that doesn't follow the contract v1 record shape gives an empty context whose
    `notes` say why, so the failure is visible to M2 and in the pipeline output instead of
    stopping the whole run.
    """
    try:
        parsed = parse_records(decode_tsv(telemetry.content))
        signals = extract_anomalies(parsed, thresholds)
    except (IngestError, ValueError) as error:
        return SemanticContext(strategy=STRATEGY, notes=f"M1 could not read the telemetry: {error}")

    return SemanticContext(
        strategy=STRATEGY,
        kept_signals=signals,
        anomalies=[f"{signal.service}: {signal.name} ({signal.evidence})" for signal in signals],
        services=sorted({signal.service for signal in signals}),
        notes=(
            f"Stage 1 only: {len(signals)} anomalies from {parsed.total} records. "
            "Graph-based pruning (F2) is not built yet."
        ),
    )
