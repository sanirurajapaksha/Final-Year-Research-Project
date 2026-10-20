"""M2's LLMClient on top of the team's shared OpenRouter client (argus.llm.client.complete_json).

Why an adapter: the loop only knows `structured(task, schema, **variables)`, so it can't depend on one
provider, and tests use FakeLLM. This class turns that call into one complete_json request:
  task + variables -> prompt (prompts.PROMPTS), pydantic schema -> strict JSON Schema,
  reply -> validated pydantic object, tokens -> `usage`.
Failures are mapped to what the controller already falls back on:
  no template, no key, network error, timeout -> LLMUnavailable;  a reply that doesn't validate -> ValueError.
Each call is also kept in `calls` (task, prompt version, model, tokens, raw reply) for the trajectory log.
"""

import copy
import os

from pydantic import BaseModel

from argus.diagnosis.ports.base import LLMUnavailable, T
from argus.diagnosis.prompts import PROMPTS
from argus.llm.client import LLMError, complete_json

# The shared client's 300-token default is too short for several hypotheses with commands: a reply cut
# short no longer matches the schema. 30 s leaves room inside M2's 900 s budget.
MAX_TOKENS = 1000
TIMEOUT_S = 30.0


def strict_schema(model: type[BaseModel]) -> dict:
    """The model's JSON Schema in the form OpenRouter's strict mode accepts.

    Strict mode needs every object closed (`additionalProperties: false`) with every property required,
    and rejects `default`. A free-form dict field (dict[str, X]) can't be written that way, so it is
    refused here rather than at the provider: give the LLM a list of {key, value} items instead.
    """
    schema = copy.deepcopy(model.model_json_schema())
    _close(schema, model.__name__)
    for name, sub in schema.get("$defs", {}).items():
        _close(sub, name)
    return schema


def _close(node, where: str) -> None:
    if isinstance(node, list):
        for item in node:
            _close(item, where)
        return
    if not isinstance(node, dict):
        return
    node.pop("default", None)
    node.pop("title", None)
    if node.get("type") == "object":
        extra = node.get("additionalProperties")
        if isinstance(extra, dict) or (extra is True) or ("properties" not in node and extra is not False):
            raise ValueError(f"{where}: free-form object fields don't fit strict mode; use a list of items")
        node["additionalProperties"] = False
        node["required"] = list(node.get("properties", {}))
    for key, value in node.items():
        if key != "$defs":
            _close(value, where)


class OpenRouterLLM:
    """LLMClient for the real model. Construct it only when a key and a model are configured."""

    def __init__(self, model: str, timeout_s: float = TIMEOUT_S, max_tokens: int = MAX_TOKENS) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.usage = {"calls": 0, "failed": 0, "prompt_tokens": 0, "completion_tokens": 0}
        self.calls: list[dict] = []

    def structured(self, task: str, schema: type[T], **variables) -> T:
        template = PROMPTS.get(task)
        if template is None:
            raise LLMUnavailable(f"no prompt for task {task!r}")
        prompt = template.render(**variables)
        self.usage["calls"] += 1
        try:
            text, usage = complete_json(
                prompt,
                strict_schema(schema),
                self.model,
                template.timeout_s or self.timeout_s,
                template.max_tokens or self.max_tokens,
                reasoning=template.reasoning,
            )
        except LLMError as exc:
            self.usage["failed"] += 1
            self._keep(task, template.version, {}, f"error: {exc}")
            raise LLMUnavailable(f"{task}: {exc}") from exc
        self.usage["prompt_tokens"] += int(usage.get("prompt_tokens", 0) or 0)
        self.usage["completion_tokens"] += int(usage.get("completion_tokens", 0) or 0)
        self._keep(task, template.version, usage, text)
        if not text:  # a reasoning model that thought until max_tokens ran out sends no answer at all
            self.usage["failed"] += 1
            raise LLMUnavailable(f"{task}: empty reply, the token budget ran out before the answer")
        try:
            return schema.model_validate_json(text)
        except ValueError:  # pydantic's ValidationError: the controller falls back to rules
            self.usage["failed"] += 1
            raise

    def _keep(self, task: str, version: str, usage: dict, reply: str) -> None:
        self.calls.append(
            {"task": task, "prompt_version": version, "model": self.model, "usage": usage, "reply": reply}
        )


def llm_from_env(model: str):
    """OpenRouterLLM when ARGUS_LLM_API_KEY and a model are set, otherwise None (the loop uses rules)."""
    if os.environ.get("ARGUS_LLM_API_KEY") and model:
        return OpenRouterLLM(model)
    return None
