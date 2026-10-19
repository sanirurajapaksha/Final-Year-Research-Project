"""Offline and test plugs for the ports: no network, no API key, same answers every run."""

from argus.diagnosis.ports.base import LLMUnavailable, ReadResult, T


class NoLLM:
    """Default when no model is configured: every task falls back to rules."""

    def __init__(self) -> None:
        self.usage = {"calls": 0}

    def structured(self, task: str, schema: type[T], **variables) -> T:
        raise LLMUnavailable(task)


class NullReadExecutor:
    """Default when no cluster is connected: every read is unavailable, so evidence is neutral."""

    def run(self, command: str) -> ReadResult:
        return ReadResult(output="unavailable", ok=False)


class FakeLLM:
    """Scripted model for tests: answers each task from a queue, in order, then runs out."""

    def __init__(self, answers: dict[str, list[dict]]) -> None:
        self._answers = {task: list(queue) for task, queue in answers.items()}
        self.usage = {"calls": 0}
        self.prompts: list[tuple[str, dict]] = []

    def structured(self, task: str, schema: type[T], **variables) -> T:
        queue = self._answers.get(task)
        if not queue:
            raise LLMUnavailable(task)
        self.prompts.append((task, variables))
        self.usage["calls"] += 1
        return schema.model_validate(queue.pop(0))


class FakeReadExecutor:
    """Canned cluster for tests: known commands return their output, others fail."""

    def __init__(self, outputs: dict[str, str]) -> None:
        self._outputs = outputs
        self.calls: list[str] = []

    def run(self, command: str) -> ReadResult:
        self.calls.append(command)
        if command in self._outputs:
            return ReadResult(output=self._outputs[command], ok=True)
        return ReadResult(output="unavailable", ok=False)
