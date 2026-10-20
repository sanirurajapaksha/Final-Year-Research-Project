import json
from pathlib import Path

import pytest

from argus.contracts import SemanticContext

CONTEXTS = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "m2" / "contexts"


@pytest.fixture
def m2_context():
    """Load an M2 context fixture by name: m2_context("cart_addr") -> (SemanticContext, truth dict)."""

    def load(name: str) -> tuple[SemanticContext, dict]:
        data = json.loads((CONTEXTS / f"{name}.json").read_text(encoding="utf-8"))
        return SemanticContext.model_validate(data["context"]), data["truth"]

    return load
