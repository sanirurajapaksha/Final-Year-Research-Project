"""M1's output: the Semantic Context Object (M1 -> M4 -> M2)."""

from pydantic import BaseModel


class SemanticContext(BaseModel):
    """Filtered, structured view of the incident that M2 diagnoses from."""

    anomalies: list[str] = []
    services: list[str] = []
    # Edges of the Service Dependency Graph as (caller, callee) pairs.
    dependencies: list[tuple[str, str]] = []
    notes: str = ""
