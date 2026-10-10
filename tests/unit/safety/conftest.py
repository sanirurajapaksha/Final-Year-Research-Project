import json
from pathlib import Path

import pytest

M3_FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "m3"


@pytest.fixture
def snapshot() -> dict:
    return json.loads((M3_FIXTURES / "snapshot_hotel_reservation.json").read_text(encoding="utf-8"))
