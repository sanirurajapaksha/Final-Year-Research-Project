import pytest

from argus.diagnosis.core.models import Candidate, DiagContext
from argus.diagnosis.loop.clues import LOWEST, NONE, STRONG, WEAK, layer_score
from argus.diagnosis.loop.context_adapter import adapt
from argus.diagnosis.loop.generator import RuleGenerator


def ctx(*symptoms, status=None):
    return DiagContext(
        namespace="ns",
        candidates=[Candidate(service="cart")],
        symptoms=list(symptoms),
        node_status=status or {},
    )


def test_your_m1_log_points_at_config_then_network_then_resources(m2_context):
    context, _ = m2_context("cart_addr")
    diag = adapt(context, "ns")
    scores = {layer: layer_score("cart", layer, diag) for layer in ("app-config", "k8s-network", "resources")}
    assert scores == {"app-config": STRONG, "k8s-network": WEAK, "resources": LOWEST}  # cart is Running


def test_repeating_a_line_does_not_raise_the_score():
    line = "cart: log_error (failed to connect to redis: timeout)"
    assert layer_score("cart", "k8s-network", ctx(line)) == layer_score(
        "cart", "k8s-network", ctx(*[line] * 100)
    )


def test_only_the_services_own_lines_count():
    other = ctx("frontend: log_error (CART_ADDR environment variable not set)")
    assert layer_score("cart", "app-config", other) == NONE


def test_the_service_name_in_the_prefix_cannot_match_a_clue():
    # "env" is a weak config clue; a service called "envoy" must not match itself
    assert layer_score("envoy", "app-config", ctx("envoy: http_5xx_rate (0.4 > 0.05)")) == NONE


def test_pod_status_counts_as_evidence(m2_context):
    context, _ = m2_context("misleading")  # log blames config, but the pod is crash-looping
    diag = adapt(context, "ns")
    assert layer_score("cart", "resources", diag) == STRONG
    assert layer_score("cart", "app-config", diag) == STRONG  # a tie: the reads have to decide


def test_scores_stay_inside_the_caps_and_unknown_layers_are_neutral():
    for layer in ("app-config", "k8s-network", "resources"):
        assert 0.1 <= layer_score("cart", layer, ctx("cart: OOMKilled not set timeout")) <= 0.9
    assert layer_score("cart", "dependency", ctx()) == pytest.approx(0.5)


def test_rule_generator_puts_the_best_supported_layer_first(m2_context):
    context, _ = m2_context("cart_addr")
    hyps = RuleGenerator().draft(adapt(context, "ns"), k=3)
    assert [(h.layer, h.confidence) for h in hyps] == [
        ("app-config", STRONG),
        ("k8s-network", WEAK),
        ("resources", LOWEST),
    ]


def test_without_clues_every_guess_is_half(m2_context):
    context, _ = m2_context("cart_addr")
    hyps = RuleGenerator(use_clues=False).draft(adapt(context, "ns"), k=3)
    assert [h.confidence for h in hyps] == [0.5, 0.5, 0.5]
