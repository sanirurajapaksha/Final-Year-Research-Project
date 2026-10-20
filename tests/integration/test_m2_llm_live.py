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


def test_real_model_scores_the_scenario_01_reads_like_the_rules_do():
    """5.3: on scenario_01's three canned reads the model should agree with RuleScorer."""
    import json
    from pathlib import Path

    from argus.diagnosis.loop.controller import ScoreAnswer

    reads = json.loads(
        (Path(__file__).resolve().parents[2] / "data/fixtures/m2/scenario_01/reads.json").read_text(
            encoding="utf-8"
        )
    )["reads"]
    hypotheses = {
        "H1": "cart [app-config] missing or wrong dependency address env var | expects: CART_ADDR absent",
        "H2": "cart [k8s-network] Service selects no ready pods | expects: no ready addresses",
        "H3": "cart [resources] container OOMKilled or crash-looping | expects: OOMKilled or CrashLoop",
    }
    expected = {
        "kubectl get deployment cart -n default -o json": ("H1", "strong-support"),
        "kubectl get endpoints cart -n default": ("H2", "strong-refute"),
        "kubectl describe pods -n default -l app=cart": ("H3", "strong-refute"),
    }
    llm = OpenRouterLLM(os.environ["ARGUS_LLM_MODEL"])
    for command, (hyp, verdict) in expected.items():
        answer = llm.structured(
            "score", ScoreAnswer, command=command, output=reads[command], hypotheses=hypotheses
        )
        assert answer.by_id().get(hyp) == verdict, (command, answer.by_id())
