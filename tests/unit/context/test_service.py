from argus.context.service import build_context
from argus.contracts import CompressedTelemetry, SemanticContext


def test_build_context_returns_a_semantic_context():
    telemetry = CompressedTelemetry(content="", original_size=0, compressed_size=0)
    assert isinstance(build_context(telemetry), SemanticContext)
