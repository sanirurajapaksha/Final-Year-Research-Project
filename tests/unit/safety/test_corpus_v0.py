"""Checks that corpus v0 is well-formed. It doesn't run M3 on it (that is the evaluation)."""

import json
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[3] / "data" / "corpora" / "m3_v0"
FIELDS = [
    "id",
    "group",
    "verb",
    "command",
    "snapshot",
    "label",
    "category",
    "reason",
    "labelled_by",
    "review",
]


def load_commands() -> list[dict]:
    return json.loads((CORPUS / "commands.json").read_text(encoding="utf-8"))


def test_every_command_has_the_fields_and_a_valid_label():
    for row in load_commands():
        assert list(row) == FIELDS, row["id"]
        assert (CORPUS / row["snapshot"]).exists(), row["id"]
        if row["label"] == "unsafe":
            assert row["category"] in (1, 2, 3, 4), row["id"]
        else:
            assert row["label"] == "safe", row["id"]
            assert row["category"] is None, row["id"]
        assert row["review"] in ("draft", "reviewed"), row["id"]


def test_ids_are_unique():
    ids = [row["id"] for row in load_commands()]
    assert len(ids) == len(set(ids))
