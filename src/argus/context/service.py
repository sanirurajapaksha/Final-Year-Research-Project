"""M1 entry point.

STUB: replace the body. Keep the signature until contract v1 changes it.
"""

from argus.contracts import CompressedTelemetry, SemanticContext


def build_context(telemetry: CompressedTelemetry) -> SemanticContext:
    """Turn M4's compressed telemetry into the Semantic Context Object for M2."""
    return SemanticContext(notes="stub: M1 not implemented yet")
