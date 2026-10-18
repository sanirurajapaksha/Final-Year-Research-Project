"""The two sockets M2 plugs the outside world into, and the read-only guard.

The loop only talks to these, so any LLM or cluster backend can be swapped in without
changing it.
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

from argus.diagnosis.core.readonly import is_read_only

T = TypeVar("T", bound=BaseModel)


class ReadResult(BaseModel):
    """What came back from one read command."""

    output: str
    ok: bool
    latency_ms: float = 0.0


class ReadExecutor(Protocol):
    """Anything that can run one read command on the cluster."""

    def run(self, command: str) -> ReadResult: ...


class LLMClient(Protocol):
    """Anything that can answer one task with a validated object of the given schema."""

    usage: dict[str, int]

    def structured(self, task: str, schema: type[T], **variables) -> T: ...


class LLMUnavailable(Exception):
    """No LLM answer; the caller switches to its rule-based fallback."""


def guarded_run(reads: ReadExecutor, command: str) -> ReadResult:
    """The only way M2 runs a read: anything not read-only never reaches the executor."""
    if not is_read_only(command):
        return ReadResult(output="blocked: not read-only", ok=False)
    try:
        return reads.run(command)
    except Exception as e:  # a broken tool gives neutral evidence, never a crash
        return ReadResult(output=f"error: {e}", ok=False)
