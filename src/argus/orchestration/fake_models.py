"""Deterministic fake model calls with simulated time; no network or sleeping."""

from collections import deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass

from argus.orchestration.model_dispatch import AdapterReply
from argus.orchestration.router import CandidateEstimate, RoutingTask


@dataclass(frozen=True)
class FakeStep:
    output: object = None
    elapsed_ms: int = 0
    error: Exception | None = None

    def __post_init__(self):
        if type(self.elapsed_ms) is not int or self.elapsed_ms < 0:
            raise ValueError("fake elapsed_ms must be a nonnegative integer")
        if self.error is not None and not isinstance(self.error, Exception):
            raise ValueError("fake error must be an exception")
        if self.error is not None and self.output is not None:
            raise ValueError("a fake step cannot contain both output and an error")


@dataclass(frozen=True)
class FakeCall:
    task_id: str
    model_id: str
    prompt: str
    timeout_ms: int


class ScriptedAdapter:
    """Consume caller-supplied steps per task/model; an exhausted script errors."""

    def __init__(self, scripts: Mapping[tuple[str, str], Sequence[FakeStep]]):
        self._scripts = {
            key: deque(FakeStep(deepcopy(step.output), step.elapsed_ms, step.error) for step in steps)
            for key, steps in scripts.items()
        }
        self._calls: list[FakeCall] = []

    @property
    def calls(self) -> tuple[FakeCall, ...]:
        return tuple(self._calls)

    def call(
        self, task: RoutingTask, candidate: CandidateEstimate, prompt: str, *, timeout_ms: int
    ) -> AdapterReply:
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        if task.task_id != candidate.task_id:
            raise ValueError("candidate does not belong to task")
        self._calls.append(FakeCall(task.task_id, candidate.model_id, prompt, timeout_ms))
        steps = self._scripts.get((task.task_id, candidate.model_id))
        if not steps:
            raise RuntimeError("no remaining fake response for task/model")
        step = steps.popleft()
        if step.elapsed_ms > timeout_ms:
            raise TimeoutError("simulated model deadline exceeded")
        if step.error is not None:
            raise step.error
        return AdapterReply(deepcopy(step.output), step.elapsed_ms)
