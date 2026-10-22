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


# ---------- review #40: whole words, and fixtures the table wasn't written from ----------


def test_access_log_address_fields_are_not_a_config_clue():
    # remote_addr / peer_addr are ordinary access-log fields, not a missing env var.
    line = "cart: log_error (request failed remote_addr=10.0.0.4 peer_addr=10.0.0.9)"
    assert layer_score("cart", "app-config", ctx(line)) == NONE


def test_an_upper_case_address_variable_is_a_strong_config_clue():
    for var in ("PAYMENT_ADDR", "DB_HOST", "AUTH_URL"):
        assert layer_score("cart", "app-config", ctx(f"cart: log_error ({var} is empty)")) == STRONG, var


def test_phrases_match_whole_words_only():
    assert layer_score("cart", "app-config", ctx("cart: log_error (envoy upstream reset)")) == NONE
    assert layer_score("cart", "app-config", ctx("cart: log_error (configmap reloaded)")) == NONE
    assert layer_score("cart", "app-config", ctx("cart: log_error (bad config value)")) == WEAK
    assert layer_score("cart", "k8s-network", ctx("cart: log_error (timeout: 5s)")) == WEAK


@pytest.mark.parametrize(
    "name, service, expected",
    [
        # redis_down: the error is a refused connection, not a setting
        ("redis_down", "cart", {"app-config": NONE, "k8s-network": STRONG, "resources": LOWEST}),
        # chain4: cart names its own env var; checkout only reports that cart is unavailable
        ("chain4", "cart", {"app-config": STRONG, "k8s-network": NONE, "resources": NONE}),
        ("chain4", "checkout", {"app-config": NONE, "k8s-network": WEAK, "resources": NONE}),
        # misleading: the log blames a setting, the pod status says crash loop; the reads must decide
        ("misleading", "cart", {"app-config": STRONG, "k8s-network": NONE, "resources": STRONG}),
    ],
)
def test_clues_on_the_other_fixtures(m2_context, name, service, expected):
    context, _ = m2_context(name)
    diag = adapt(context, "ns")
    assert {layer: layer_score(service, layer, diag) for layer in expected} == expected


# ---------- review #40 (2nd round): M1's own signal names, word endings, and Running ----------


def m1_stage1_context():
    """M1's real Stage 1 output on scenario_01: it keeps the memory spike and the restarts (noise)."""
    from pathlib import Path

    from argus.context.service import build_context
    from argus.contracts import TelemetryBatch
    from argus.orchestration.service import compress

    path = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "m1" / "scenario_01" / "telemetry.json"
    batch = TelemetryBatch.model_validate_json(path.read_text(encoding="utf-8"))
    return adapt(build_context(compress(batch), strategy="stage1"), "ns")


def test_m1_resource_signal_lines_are_weak_resource_clues():
    diag = m1_stage1_context()
    assert "product-catalog: memory_utilization (memory_utilization=0.94 > 0.9)" in diag.symptoms
    assert layer_score("product-catalog", "resources", diag) == WEAK
    assert layer_score("metrics-server", "resources", diag) == WEAK  # restart_count ... restarted 6 times


@pytest.mark.parametrize(
    "line, layer",
    [
        ("cart: memory_utilization (memory_utilization=0.94 > 0.9)", "resources"),
        ("cart: cpu_utilization (cpu_utilization=0.97 > 0.9)", "resources"),
        ("cart: restart_count (Pod cart-6b7c9 restarted 6 times)", "resources"),
        ("cart: log_error (container restarts: 4)", "resources"),
        ("cart: log_error (upstream timeouts after 5s)", "k8s-network"),
    ],
)
def test_a_running_pod_does_not_hide_a_resource_or_network_signal(line, layer):
    running = ctx(line, status={"cart": "Running"})
    assert layer_score("cart", layer, running) == WEAK


def test_a_running_pod_with_no_resource_signal_still_lowers_resources():
    running = ctx("cart: log_error (CART_ADDR environment variable not set)", status={"cart": "Running"})
    assert layer_score("cart", "resources", running) == LOWEST


def test_endings_do_not_make_unrelated_words_match():
    assert layer_score("cart", "app-config", ctx("cart: log_error (envoy upstream reset)")) == NONE
    assert layer_score("cart", "resources", ctx("cart: log_error (restartable job queued)")) == NONE
