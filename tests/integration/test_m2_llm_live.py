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


def test_real_model_drafts_the_cart_config_hypothesis_from_your_m1_log():
    """Step 6: on the cart_addr fixture the model should propose cart/app-config with a usable read."""
    import json
    from pathlib import Path

    from argus.contracts import SemanticContext
    from argus.diagnosis.loop.context_adapter import adapt
    from argus.diagnosis.loop.llm_generator import LLMGenerator

    fixture = Path(__file__).resolve().parents[2] / "data/fixtures/m2/contexts/cart_addr.json"
    context = SemanticContext.model_validate(json.loads(fixture.read_text(encoding="utf-8"))["context"])
    llm = OpenRouterLLM(os.environ["ARGUS_LLM_MODEL"])

    hyps = LLMGenerator(llm).draft(adapt(context, "default", scheme="hop"), k=3)

    from_llm = [h for h in hyps if h.source == "llm"]
    assert from_llm, llm.calls[-1]["reply"]  # at least one usable LLM hypothesis
    assert ("cart", "app-config") in {(h.component, h.layer) for h in from_llm}


def test_real_model_fills_the_env_patch_from_the_service_list():
    """Step 7: given the confirmed cart/app-config diagnosis, the model should fill CART_ADDR=redis-cart:6379
    from the canned service list, cite it, and so produce the exact patch the rules produce."""
    import json
    from pathlib import Path

    from argus.contracts import SemanticContext
    from argus.diagnosis.core.models import Evidence, HypothesisSpec
    from argus.diagnosis.demo import scenario_reads
    from argus.diagnosis.loop.context_adapter import adapt
    from argus.diagnosis.loop.fixes import patch_env_command
    from argus.diagnosis.loop.llm_fixer import FixProposer

    root = Path(__file__).resolve().parents[2]
    context = SemanticContext.model_validate(
        json.loads((root / "data/fixtures/m2/contexts/cart_addr.json").read_text(encoding="utf-8"))["context"]
    )
    ctx = adapt(context, "default", scheme="hop")
    reads = scenario_reads()
    deployment = "kubectl get deployment cart -n default -o json"
    top = HypothesisSpec(
        id="H1",
        component="cart",
        layer="app-config",
        fault="CART_ADDR env var missing",
        test=deployment,
        expected="no CART_ADDR in the cart container env",
    )
    e1 = Evidence(id="E1", hyp_id="H1", command=deployment, output=reads.run(deployment).output, ok=True)
    llm = OpenRouterLLM(os.environ["ARGUS_LLM_MODEL"])

    outcome = FixProposer(llm, reads).propose(top, ctx, [e1], {})

    assert outcome.source == "llm", [c["reply"] for c in llm.calls]
    assert outcome.action.command == patch_env_command("cart", "CART_ADDR", "redis-cart:6379", "default")
    assert "L1" in outcome.action.rationale


def test_real_model_writes_a_report_that_passes_the_checks():
    """Step 8: a confirmed diagnosis with a fix; the note must cite real ids, name cart, fit 120 words."""
    from argus.contracts import ProposedAction
    from argus.diagnosis.core.models import Candidate, DiagContext, Evidence, HypothesisSpec
    from argus.diagnosis.loop.report import ReportWriter

    ctx = DiagContext(
        namespace="default",
        candidates=[Candidate(service="cart")],
        symptoms=["cart: log_error (failed to connect to redis: CART_ADDR environment variable not set)"],
    )
    top = HypothesisSpec(
        id="H1",
        component="cart",
        layer="app-config",
        fault="CART_ADDR env var missing",
        test="kubectl get deployment cart -n default -o json",
    )
    e1 = Evidence(
        id="E1",
        hyp_id="H1",
        command=top.test,
        output='{"containers": [{"name": "cart", "env": []}]}',
        ok=True,
    )
    fix = ProposedAction(
        command="kubectl patch deployment cart -n default -p '{...CART_ADDR=redis-cart:6379...}'",
        is_write=True,
    )
    llm = OpenRouterLLM(os.environ["ARGUS_LLM_MODEL"])

    text, source = ReportWriter(llm).write(
        top, 0.85, True, "confident", [e1], {"E1": "strong-support"}, fix, "", ctx
    )

    assert source == "llm", [c["reply"] for c in llm.calls]
    print(text)
