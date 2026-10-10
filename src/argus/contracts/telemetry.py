"""Telemetry as it enters the system (benchmark -> M4) and after M4 compresses it (M4 -> M1)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TelemetryBatch(BaseModel):
    """Raw telemetry from the benchmark environment, before any processing."""

    source: str
    collected_at: datetime
    records: list[dict[str, Any]] = []


class CompressedTelemetry(BaseModel):
    """M4's preprocessed and compressed telemetry, handed to M1.

    Fields that M1 or M3 rely on must survive compression unchanged (lossless for those fields).
    """

    format: str = "tsv"
    content: str
    original_size: int
    compressed_size: int
