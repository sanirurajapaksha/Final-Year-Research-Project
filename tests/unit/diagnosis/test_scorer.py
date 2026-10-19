from argus.diagnosis.core.models import Candidate, DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.loop.scorer import RuleScorer

CART_LOG = "cart: log_error (failed to connect to redis: CART_ADDR environment variable not set)"
CTX = DiagContext(namespace="default", candidates=[Candidate(service="cart")], symptoms=[CART_LOG])
YAML = "kubectl get deployment cart -n default -o yaml"
ENDPOINTS = "kubectl get endpoints cart -n default"
DESCRIBE = "kubectl describe pods -n default -l app=cart"
HYPS = {
    "H1": HypothesisSpec(component="cart", layer="app-config", fault="f", test=YAML),
    "H2": HypothesisSpec(component="cart", layer="k8s-network", fault="f", test=ENDPOINTS),
    "H3": HypothesisSpec(component="cart", layer="resources", fault="f", test=DESCRIBE),
}


def score(command: str, output: str, ctx: DiagContext = CTX) -> dict[str, str]:
    evidence = Evidence(id="E1", hyp_id="H1", command=command, output=output, ok=True)
    return RuleScorer().score(evidence, HYPS, ctx)


def test_missing_address_supports_the_config_fault():
    assert score(YAML, "containers:\n- name: cart\n  image: otel/demo:cart") == {"H1": "strong-support"}


def test_address_present_refutes_the_config_fault():
    assert score(YAML, "env:\n- name: CART_ADDR\n  value: redis-cart:6379") == {"H1": "strong-refute"}


def test_no_address_in_the_evidence_stays_neutral():
    ctx = CTX.model_copy(update={"symptoms": ["cart: http_5xx_rate (0.92 > 0.05)"]})
    assert score(YAML, "containers: []", ctx) == {}


def test_endpoints_none_supports_and_an_address_refutes():
    assert score(ENDPOINTS, "NAME   ENDPOINTS   AGE\ncart   <none>   3d") == {"H2": "strong-support"}
    assert score(ENDPOINTS, "NAME   ENDPOINTS   AGE\ncart   10.244.0.12:7070   3d") == {"H2": "strong-refute"}


def test_crash_supports_and_running_refutes_the_resources_fault():
    assert score(DESCRIBE, "Reason: CrashLoopBackOff") == {"H3": "strong-support"}
    assert score(DESCRIBE, "Last State: Terminated\n  Reason: OOMKilled") == {"H3": "strong-support"}
    assert score(DESCRIBE, "Status: Running\nRestart Count: 0") == {"H3": "strong-refute"}


def test_only_the_hypothesis_whose_test_ran_is_judged():
    verdicts = score(YAML, "containers: []")
    assert set(verdicts) == {"H1"}  # H2 and H3 weren't tested by this read


def test_unreadable_output_stays_neutral():
    assert score(DESCRIBE, "Error from server (NotFound)") == {}
