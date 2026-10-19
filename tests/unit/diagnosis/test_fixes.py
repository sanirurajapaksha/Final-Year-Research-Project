from argus.diagnosis.core.models import Candidate, DiagContext, HypothesisSpec
from argus.diagnosis.core.readonly import META
from argus.diagnosis.loop.fixes import address_var, propose_fix

CART_LOG = "cart: log_error (failed to connect to redis: CART_ADDR environment variable not set)"
CTX = DiagContext(namespace="default", candidates=[Candidate(service="cart")], symptoms=[CART_LOG])
FIX = (
    "kubectl patch deployment cart -n default -p "
    '\'{"spec":{"template":{"spec":{"containers":[{"name":"cart","env":'
    '[{"name":"CART_ADDR","value":"redis-cart:6379"}]}]}}}}\''
)


def spec(layer: str, component: str = "cart") -> HypothesisSpec:
    return HypothesisSpec(component=component, layer=layer, fault="f", test="kubectl get pods -n default")


def test_missing_address_gets_the_env_patch():
    fix = propose_fix(spec("app-config"), CTX)
    assert fix.command == FIX
    assert fix.is_write and fix.target_namespace == "default"


def test_network_and_resource_faults_get_a_rolling_restart():
    for layer in ("k8s-network", "resources"):
        fix = propose_fix(spec(layer), CTX)
        assert fix.command == "kubectl rollout restart deployment/cart -n default"


def test_unknown_address_proposes_nothing():
    ctx = CTX.model_copy(update={"symptoms": ["cart: log_error (PAYMENT_ADDR environment variable not set)"]})
    assert propose_fix(spec("app-config"), ctx) is None


def test_no_address_in_the_evidence_proposes_nothing():
    ctx = CTX.model_copy(update={"symptoms": ["cart: http_5xx_rate (0.92 > 0.05)"]})
    assert propose_fix(spec("app-config"), ctx) is None


def test_unknown_layer_proposes_nothing():
    assert propose_fix(spec("storage"), CTX) is None


def test_address_var_only_reads_the_components_own_lines():
    assert address_var("cart", [CART_LOG]) == "CART_ADDR"
    assert address_var("frontend", [CART_LOG]) is None


def test_every_write_is_one_plain_command_with_a_namespace():
    for layer in ("app-config", "k8s-network", "resources"):
        command = propose_fix(spec(layer), CTX).command
        assert " -n default" in command
        assert not any(m in command for m in META)