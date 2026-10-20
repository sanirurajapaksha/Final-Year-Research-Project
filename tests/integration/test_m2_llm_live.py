"""One real call through M2's adapter to the team's model. Skipped unless the shell has a key and model.

Run it by hand after changing the adapter or the model:
    ARGUS_LLM_API_KEY=... ARGUS_LLM_MODEL=deepseek/... pytest tests/integration/test_m2_llm_live.py
It costs one short request.
"""

import os
from typing import Literal

import pytest
from pydantic import BaseModel

from argus.diagnosis.ports.openrouter import OpenRouterLLM
from argus.diagnosis.prompts import PROMPTS, Template, untrusted_note, wrap

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ARGUS_LLM_API_KEY") and os.environ.get("ARGUS_LLM_MODEL")),
    reason="live LLM test: set ARGUS_LLM_API_KEY and ARGUS_LLM_MODEL to run it",
)


class Layer(BaseModel):
    layer: Literal["app-config", "k8s-network", "resources"]


def render(line: str) -> str:
    return "\n".join(
        [
            "Which fault layer does this log line point at? Answer with JSON only.",
            wrap("signals", line),
            untrusted_note("signals"),
        ]
    )


def test_one_real_call_returns_valid_json(monkeypatch):
    monkeypatch.setitem(PROMPTS, "smoke", Template("smoke", "smoke-v1", render))
    llm = OpenRouterLLM(os.environ["ARGUS_LLM_MODEL"])

    answer = llm.structured("smoke", Layer, line="cart: CART_ADDR environment variable not set")

    assert answer.layer == "app-config"
    assert llm.usage["calls"] == 1 and llm.usage["prompt_tokens"] > 0
