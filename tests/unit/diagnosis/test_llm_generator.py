"""Step 6: the LLM hypothesis generator, with FakeLLM playing the model."""

import pytest

from argus.diagnosis.core.config import preset
from argus.diagnosis.core.models import Candidate, DiagContext
from argus.diagnosis.loop.context_adapter import adapt
from argus.diagnosis.loop.controller import Controller
from argus.diagnosis.loop.generator import RuleGenerator, validate
from argus.diagnosis.loop.llm_generator import LLMGenerator
from argus.diagnosis.ports.fakes import FakeLLM, FakeReadExecutor, NoLLM
from argus.diagnosis.prompts import render_draft
from argus.diagnosis.service import diagnose_report

CART_CONFIG = {
    "component": "cart",
    "layer": "app-config",
    "fault": "CART_ADDR env var missing",
    "test": "kubectl get deployment cart -n ns -o json",
    "expected": "no CART_ADDR in the cart container env",
    "confidence": "high",
}
REDIS_DOWN = {
    "component": "redis",
    "layer": "dependency",
    "fault": "redis has no ready pods",
    "test": "kubectl get endpoints redis -n ns",
    "expected": "<none> in the ENDPOINTS column",
    "confidence": "medium",
}
CART_NETWORK = {
    "component": "cart",
    "layer": "k8s-network",
    "fault": "cart Service selects no ready pods",
    "test": "kubectl get endpoints cart -n ns",
    "expected": "<none> in the ENDPOINTS column",
    "confidence": "low",
}


def hop_ctx(m2_context, name="cart_addr"):
    context, _ = m2_context(name)
    return adapt(context, "ns", scheme="hop")


def draft_prompt(ctx, refuted=()):
    return render_draft(
        candidates=[c.model_dump() for c in ctx.candidates],
        failing_path=ctx.failing_path,
        signals=ctx.symptoms,
        pod_status=ctx.node_status,
        refuted=list(refuted),
        k=3,
        namespace=ctx.namespace,
    )


# ---------- the prompt ----------


def test_prompt_labels_every_candidate_with_its_hop_role(m2_context):
    prompt = draft_prompt(hop_ctx(m2_context))
    assert "cart: origin: the deepest failing service" in prompt
    assert "frontend: upstream caller on the failing path, 1 hop above the origin" in prompt
    assert "redis: quiet dependency, 1 hop below the origin" in prompt
    assert "Do NOT lower confidence because of where the component sits" in prompt


def test_prompt_shows_no_weights(m2_context):
    assert "1.5" not in draft_prompt(hop_ctx(m2_context))  # position is weighted in code, not by the LLM


def test_prompt_carries_signals_pod_status_and_refuted(m2_context):
    prompt = draft_prompt(hop_ctx(m2_context), refuted=["cart: CART_ADDR env var missing"])
    signals = prompt[prompt.index("<signals>") : prompt.index("</signals>")]
    assert "CART_ADDR environment variable not set" in signals and "cart pod status: Running" in signals
    assert "cart: CART_ADDR env var missing" in prompt[prompt.index("<refuted>") :]
    assert "-n ns" in prompt


# ---------- the generator ----------


def test_llm_hypotheses_are_used_with_word_confidences(m2_context):
    llm = FakeLLM({"draft": [{"hypotheses": [CART_CONFIG, REDIS_DOWN, CART_NETWORK]}]})
    hyps = LLMGenerator(llm).draft(hop_ctx(m2_context), k=3)

    assert [(h.id, h.component, h.layer, h.confidence) for h in hyps] == [
        ("H1", "cart", "app-config", 0.5),
        ("H2", "redis", "dependency", 0.3),
        ("H3", "cart", "k8s-network", 0.2),
    ]
    assert {h.source for h in hyps} == {"llm"}


def test_unknown_component_write_command_and_refuted_repeat_are_dropped_then_rules_fill(m2_context):
    ghost = {**CART_CONFIG, "component": "ghost-service"}
    write = {**CART_NETWORK, "test": "kubectl rollout restart deployment cart -n ns"}
    llm = FakeLLM({"draft": [{"hypotheses": [ghost, write, CART_CONFIG, REDIS_DOWN]}]})
    refuted = {("cart", "CART_ADDR env var missing")}

    hyps = LLMGenerator(llm).draft(hop_ctx(m2_context), k=3, refuted=refuted)

    assert [h.component for h in hyps if h.source == "llm"] == ["redis"]  # the only usable one
    assert len(hyps) == 3 and {h.source for h in hyps[1:]} == {"rules"}
    pairs = [(h.component, h.layer) for h in hyps]
    assert len(set(pairs)) == len(pairs)  # the rules never repeat a component + layer the LLM took


def test_no_llm_or_garbage_reply_means_the_rules_draft(m2_context):
    ctx = hop_ctx(m2_context)
    rules = RuleGenerator().draft(ctx, k=3)
    assert LLMGenerator(NoLLM()).draft(ctx, k=3) == rules
    garbage = FakeLLM({"draft": [{"hypotheses": [{"component": "cart", "layer": "vibes"}]}]})
    assert LLMGenerator(garbage).draft(ctx, k=3) == rules


def test_ids_continue_from_earlier_rounds(m2_context):
    llm = FakeLLM({"draft": [{"hypotheses": [REDIS_DOWN]}]})
    hyps = LLMGenerator(llm).draft(hop_ctx(m2_context), k=1, next_id=4)
    assert [h.id for h in hyps] == ["H4"]


def test_a_service_named_in_the_logs_is_testable_even_without_the_hop_scheme(m2_context):
    context, _ = m2_context("cart_addr")
    ctx = adapt(context, "ns")  # almanac: redis is not a candidate
    assert "redis" not in {c.service for c in ctx.candidates}
    llm = FakeLLM({"draft": [{"hypotheses": [REDIS_DOWN]}]})
    assert [h.component for h in LLMGenerator(llm).draft(ctx, k=1)] == ["redis"]


def test_a_name_must_appear_as_a_whole_word_in_the_logs():
    ctx = DiagContext(
        namespace="ns", candidates=[Candidate(service="cart")], symptoms=["cart: redis-cart down"]
    )
    spec = RuleGenerator().draft(ctx, k=1)[0]
    assert (
        validate([spec.model_copy(update={"component": "redis"})], ctx, set(), k=1) == []
    )  # only redis-cart
    assert validate([spec.model_copy(update={"component": "redis-cart"})], ctx, set(), k=1)


# ---------- 6.6: your M1 log end to end ----------


def test_your_m1_log_starts_at_47_19_19_15_and_stops_after_two_reads(m2_context):
    ctx = hop_ctx(m2_context)
    llm = FakeLLM(
        {
            "draft": [{"hypotheses": [CART_CONFIG, REDIS_DOWN, CART_NETWORK]}],
            "score": [
                {"verdicts": [{"id": "H1", "verdict": "strong-support"}, {"id": "H2", "verdict": "neutral"}]},
                {"verdicts": [{"id": "H2", "verdict": "strong-refute"}]},
            ],
        }
    )
    reads = FakeReadExecutor(
        {
            CART_CONFIG["test"]: '{"env": []}',
            REDIS_DOWN["test"]: "NAME    ENDPOINTS        AGE\nredis   10.0.0.9:6379    3d",
        }
    )

    result = Controller(preset("A5-hop", namespace="ns"), llm=llm, reads=reads).run(ctx)

    start = result.belief.history[0]["belief"]
    assert start == {
        "H1": pytest.approx(0.472, abs=1e-3),  # cart config: high (0.5) x origin (1.5)
        "H2": pytest.approx(0.189, abs=1e-3),  # redis down: medium (0.3) x quiet dependency (1.0)
        "H3": pytest.approx(0.189, abs=1e-3),  # cart network: low (0.2) x origin (1.5)
        "H0": pytest.approx(0.15),
    }
    after_first = result.belief.history[1]["belief"]["H1"]
    assert after_first == pytest.approx(0.781, abs=1e-3)  # just under the 0.80 stop line
    top, p = result.belief.ranked()[0]
    assert top == "H1" and p >= 0.80 and result.report.stop_reason == "confident"
    assert [e.hyp_id for e in result.evidence] == ["H1", "H2"]  # redis ruled out, then stop


def test_diagnose_report_marks_who_drafted_each_hypothesis(m2_context):
    context, _ = m2_context("cart_addr")
    report = diagnose_report(context, llm=FakeLLM({"draft": [{"hypotheses": [CART_CONFIG]}]}))
    sources = {(row["component"], row["layer"]): row["source"] for row in report["hypotheses"]}
    assert sources[("cart", "app-config")] == "llm"
    assert "rules" in sources.values()  # the LLM gave one usable hypothesis; the rules filled the round


def test_a_reworded_repeat_of_a_tried_idea_is_not_drafted_again(m2_context):
    ctx = hop_ctx(m2_context)
    # Round 1 tried the LLM's cart/app-config idea; round 2 falls back to the rules, whose
    # cart/app-config fault is worded differently but is the same idea with the same read.
    tried = {("cart", "CART_ADDR env var missing"), ("cart", "app-config")}
    hyps = LLMGenerator(NoLLM()).draft(ctx, k=3, refuted=tried)
    assert ("cart", "app-config") not in {(h.component, h.layer) for h in hyps}


def test_the_prompt_lists_tried_faults_not_the_layer_markers(m2_context):
    llm = FakeLLM({"draft": [{"hypotheses": [REDIS_DOWN]}]})
    LLMGenerator(llm).draft(
        hop_ctx(m2_context), k=1, refuted={("cart", "CART_ADDR missing"), ("cart", "app-config")}
    )
    assert llm.prompts[0][1]["refuted"] == ["cart: CART_ADDR missing"]
