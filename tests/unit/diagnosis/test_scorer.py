import json

from argus.diagnosis.core.models import Candidate, DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.loop.scorer import RuleScorer

CART_LOG = "cart: log_error (failed to connect to redis: CART_ADDR environment variable not set)"
CTX = DiagContext(namespace="default", candidates=[Candidate(service="cart")], symptoms=[CART_LOG])
DEPLOYMENT = "kubectl get deployment cart -n default -o json"
ENDPOINTS = "kubectl get endpoints cart -n default"
DESCRIBE = "kubectl describe pods -n default -l app=cart"
HYPS = {
    "H1": HypothesisSpec(component="cart", layer="app-config", fault="f", test=DEPLOYMENT),
    "H2": HypothesisSpec(component="cart", layer="k8s-network", fault="f", test=ENDPOINTS),
    "H3": HypothesisSpec(component="cart", layer="resources", fault="f", test=DESCRIBE),
}


def score(command: str, output: str, ctx: DiagContext = CTX) -> dict[str, str]:
    evidence = Evidence(id="E1", hyp_id="H1", command=command, output=output, ok=True)
    return RuleScorer().score(evidence, HYPS, ctx)


def deployment(env: list[dict] | None = None, container: str = "cart") -> str:
    """`kubectl get deployment -o json` output with one container and the given env."""
    spec = {"name": container, "image": "otel/demo:cart"}
    if env is not None:
        spec["env"] = env
    return json.dumps({"kind": "Deployment", "spec": {"template": {"spec": {"containers": [spec]}}}})


def test_missing_address_supports_the_config_fault():
    assert score(DEPLOYMENT, deployment()) == {"H1": "strong-support"}


def test_the_right_address_refutes_the_config_fault():
    output = deployment([{"name": "CART_ADDR", "value": "redis-cart:6379"}])
    assert score(DEPLOYMENT, output) == {"H1": "strong-refute"}


def test_a_wrong_address_supports_the_config_fault():
    output = deployment([{"name": "CART_ADDR", "value": "wrong-host:9999"}])
    assert score(DEPLOYMENT, output) == {"H1": "strong-support"}


def test_an_empty_address_supports_the_config_fault():
    assert score(DEPLOYMENT, deployment([{"name": "CART_ADDR", "value": ""}])) == {"H1": "strong-support"}


def test_an_address_from_a_secret_stays_neutral():
    output = deployment([{"name": "CART_ADDR", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}}])
    assert score(DEPLOYMENT, output) == {}


def test_an_address_m2_has_no_right_value_for_stays_neutral():
    ctx = CTX.model_copy(update={"symptoms": ["cart: log_error (REDIS_ADDR environment variable not set)"]})
    assert score(DEPLOYMENT, deployment([{"name": "REDIS_ADDR", "value": "redis:6379"}]), ctx) == {}


def test_only_the_components_own_container_counts():
    output = deployment([{"name": "CART_ADDR", "value": "redis-cart:6379"}], container="sidecar")
    assert score(DEPLOYMENT, output) == {}  # no container named cart: M2 can't tell


def test_unreadable_deployment_output_stays_neutral():
    assert score(DEPLOYMENT, "Error from server (NotFound)") == {}
    assert score(DEPLOYMENT, '{"kind": "Deployment"}') == {}


def test_no_address_in_the_evidence_stays_neutral():
    ctx = CTX.model_copy(update={"symptoms": ["cart: http_5xx_rate (0.92 > 0.05)"]})
    assert score(DEPLOYMENT, "containers: []", ctx) == {}


def test_endpoints_none_supports_and_an_address_refutes():
    assert score(ENDPOINTS, "NAME   ENDPOINTS   AGE\ncart   <none>   3d") == {"H2": "strong-support"}
    assert score(ENDPOINTS, "NAME   ENDPOINTS   AGE\ncart   10.244.0.12:7070   3d") == {"H2": "strong-refute"}


def test_crash_supports_and_running_refutes_the_resources_fault():
    assert score(DESCRIBE, "Reason: CrashLoopBackOff") == {"H3": "strong-support"}
    assert score(DESCRIBE, "Last State: Terminated\n  Reason: OOMKilled") == {"H3": "strong-support"}
    assert score(DESCRIBE, "Status: Running\nRestart Count: 0") == {"H3": "strong-refute"}


def test_only_the_hypothesis_whose_test_ran_is_judged():
    verdicts = score(DEPLOYMENT, deployment())
    assert set(verdicts) == {"H1"}  # H2 and H3 weren't tested by this read


def test_unreadable_output_stays_neutral():
    assert score(DESCRIBE, "Error from server (NotFound)") == {}


def test_endpoints_only_reads_the_components_own_row():
    ad = HypothesisSpec(component="ad", layer="k8s-network", fault="f", test=ENDPOINTS)
    evidence = Evidence(id="E1", hyp_id="H1", command=ENDPOINTS, output="", ok=True)

    def verdicts(output: str) -> dict[str, str]:
        return RuleScorer().score(evidence.model_copy(update={"output": output}), {"H1": ad}, CTX)

    header = "NAME        ENDPOINTS          AGE\n"
    assert verdicts(header + "adservice   10.244.0.9:9555    3d") == {}  # "ad" is not "adservice"
    assert verdicts(header + "cart        <none>             3d\nad   10.244.0.8:9555   3d") == {
        "H1": "strong-refute"
    }  # another service's <none> doesn't count
    assert verdicts(header + "ad          <none>             3d") == {"H1": "strong-support"}


def test_a_crash_loop_that_ended_for_another_reason_refutes_the_resources_fault():
    crashed = (
        "Reason: CrashLoopBackOff\nLast State:     Terminated\n  Reason:       Error\n  Exit Code:    14"
    )
    assert score(DESCRIBE, crashed) == {"H3": "strong-refute"}  # it stopped itself: no limit killed it
    killed = crashed.replace("14", "137")
    assert score(DESCRIBE, killed) == {"H3": "strong-support"}  # SIGKILL: the OOM killer, unlabelled


def test_enospc_in_the_last_logs_supports_a_full_volume():
    logs = "kubectl logs deployment/cart -n default --previous --tail=50"
    hyps = {"H4": HypothesisSpec(component="cart", layer="storage", fault="f", test=logs)}

    def verdicts(output: str) -> dict[str, str]:
        evidence = Evidence(id="E1", hyp_id="H4", command=logs, output=output, ok=True)
        return RuleScorer().score(evidence, hyps, CTX)

    assert verdicts("pwrite: failed to write 4096 bytes: No space left on device") == {"H4": "strong-support"}
    assert verdicts("write error: ENOSPC") == {"H4": "strong-support"}
    assert verdicts("listening on :7070") == {"H4": "weak-refute"}  # the tail may have cut it off
    assert verdicts("") == {}
