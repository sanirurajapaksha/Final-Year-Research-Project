"""Step 7: the LLM fix proposer, with FakeLLM playing the model and canned reads as the cluster."""

from argus.contracts import GateDecision, SafetyVerdict
from argus.diagnosis.core.models import Candidate, DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.demo import scenario_reads
from argus.diagnosis.loop.llm_fixer import HUMAN_NOTE, FixAnswer, FixProposer
from argus.diagnosis.ports.fakes import FakeLLM, FakeReadExecutor
from argus.diagnosis.ports.openrouter import strict_schema
from argus.diagnosis.service import diagnose_report

CART_LOG = "cart: log_error (failed to connect to redis: CART_ADDR environment variable not set)"
CTX = DiagContext(
    namespace="default",
    candidates=[Candidate(service="cart", weight=1.5), Candidate(service="frontend")],
    symptoms=[CART_LOG],
)
SERVICES = (
    "NAME         TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)    AGE\n"
    "cart         ClusterIP   10.96.12.4    <none>        7070/TCP   3d\n"
    "redis-cart   ClusterIP   10.96.33.9    <none>        6379/TCP   3d\n"
)
READS = {"kubectl get services -n default": SERVICES}
E1 = Evidence(
    id="E1",
    hyp_id="H1",
    command="kubectl get deployment cart -n default -o json",
    output='{"env": []}',
    ok=True,
)
FIX = (
    "kubectl patch deployment cart -n default -p "
    '\'{"spec":{"template":{"spec":{"containers":[{"name":"cart","env":'
    '[{"name":"CART_ADDR","value":"redis-cart:6379"}]}]}}}}\''
)
RESTART = "kubectl rollout restart deployment/cart -n default"


def hyp(layer="app-config", component="cart"):
    return HypothesisSpec(
        id="H1", component=component, layer=layer, fault="f", test="kubectl get pods -n default"
    )


def answer(template="set-env", target="cart", var="CART_ADDR", value="redis-cart:6379", cited=("L1",)):
    return {
        "template": template,
        "target": target,
        "var": var,
        "value": value,
        "cited": list(cited),
        "rationale": "CART_ADDR is missing; redis-cart serves 6379",
    }


def propose(llm, layer="app-config", blocked=None, reads=READS, component="cart", evidence=(E1,)):
    fixer = FixProposer(llm, FakeReadExecutor(dict(reads)))
    return fixer.propose(hyp(layer, component), CTX, list(evidence), blocked or {})


def test_fix_answer_fits_strict_mode():
    assert strict_schema(FixAnswer)["required"] == [
        "template",
        "target",
        "var",
        "value",
        "cited",
        "rationale",
    ]


def test_llm_fills_the_env_patch_from_the_service_list():
    llm = FakeLLM({"fix": [answer()]})
    outcome = propose(llm)

    assert outcome.source == "llm" and outcome.action.command == FIX
    assert "[evidence: L1]" in outcome.action.rationale
    assert [e.command for e in outcome.lookups] == ["kubectl get services -n default"]
    sent = llm.prompts[0][1]
    assert [e["id"] for e in sent["evidence"]] == ["E1", "L1", "S1"] and [
        t["id"] for t in sent["templates"]
    ] == ["set-env"]


def test_a_guessed_value_goes_back_with_the_reason_and_the_retry_is_used():
    llm = FakeLLM({"fix": [answer(value="redis:6379"), answer()]})  # "redis" is not in the service list
    outcome = propose(llm)

    assert outcome.action.command == FIX
    retry = llm.prompts[1][1]["rejected"]
    assert len(retry) == 1 and "never guess a value" in retry[0] and "redis:6379" in retry[0]


def test_after_every_try_fails_the_rules_decide():
    llm = FakeLLM({"fix": [answer(value="guess:1")] * 3})
    outcome = propose(llm)
    assert outcome.source == "rules" and outcome.action.command == FIX  # the rules' demo address table
    assert len(llm.prompts) == 3  # one try plus max_revisions = 2


def test_a_command_m3_blocked_is_never_proposed_again():
    block = SafetyVerdict(command=FIX, decision=GateDecision.BLOCK, reason="violates PDB")
    llm = FakeLLM({"fix": [answer(), answer(template="none")]})
    outcome = propose(llm, blocked={FIX: block})

    assert outcome.action is None and outcome.source == "none" and "found no safe fix" in outcome.note
    first = llm.prompts[0][1]["rejected"]
    assert first == [f"{FIX}: blocked by M3 (violates PDB)"]  # the model is told before its first try
    assert "already blocked" in llm.prompts[1][1]["rejected"][-1]


def test_without_an_llm_the_rules_propose_and_no_lookup_runs():
    fixer = FixProposer(reads=FakeReadExecutor(READS))
    outcome = fixer.propose(hyp(), CTX, [E1], {})
    assert outcome.source == "rules" and outcome.action.command == FIX
    assert fixer.reads.calls == [] and outcome.lookups == []


def test_a_rule_fix_m3_blocked_gives_the_blocked_note():
    block = SafetyVerdict(command=RESTART, decision=GateDecision.BLOCK, reason="SIMULATED BLOCK")
    outcome = FixProposer().propose(hyp("k8s-network"), CTX, [E1], {RESTART: block})
    assert (
        outcome.action is None and "SIMULATED BLOCK" in outcome.note and "no other safe fix" in outcome.note
    )


def test_a_code_bug_needs_a_person_and_never_asks_the_llm():
    llm = FakeLLM({"fix": [answer()]})
    outcome = propose(llm, layer="code")
    assert outcome.action is None and outcome.note == HUMAN_NOTE and llm.prompts == []


def test_a_dependency_restart_may_target_the_dependency_named_in_the_evidence():
    llm = FakeLLM({"fix": [answer(template="restart", target="redis-cart", var="", value="", cited=("E1",))]})
    redis_read = Evidence(
        id="E1",
        hyp_id="H1",
        command="kubectl get endpoints redis-cart -n default",
        output="redis-cart   <none>   3d",
        ok=True,
    )
    outcome = propose(llm, layer="dependency", evidence=(redis_read,))
    assert outcome.action.command == "kubectl rollout restart deployment/redis-cart -n default"
    assert outcome.lookups == []  # only app-config faults need the service list


def test_targets_and_citations_are_checked():
    # a network fault may only restart the diagnosed component; a target nowhere in the evidence is refused
    cases = [
        (
            answer(template="restart", target="frontend", cited=()),
            "k8s-network",
            "must be the diagnosed component",
        ),
        (answer(template="restart", target="payments", cited=()), "dependency", "appears in no read"),
        (answer(cited=("E9",)), "app-config", "does not exist"),
        (answer(var="CART_PORT"), "app-config", "not named in the evidence"),
        (answer(value="redis-cart:6379;rm"), "app-config", "characters"),
        (answer(template="restart"), "app-config", "does not fix a app-config fault"),
    ]
    for bad, layer, reason in cases:
        llm = FakeLLM({"fix": [bad, answer(template="none")]})
        propose(llm, layer=layer)
        assert reason in llm.prompts[1][1]["rejected"][-1], (layer, bad)


# ---------- 7.5: through diagnose_report, on scenario_01's canned cluster ----------


def test_your_m1_log_gets_the_env_patch_with_the_value_cited_from_a_read(m2_context):
    context, _ = m2_context("cart_addr")
    llm = FakeLLM({"fix": [answer()]})  # draft and score fall back to rules; fix is the LLM
    report = diagnose_report(context, llm=llm, reads=scenario_reads())

    writes = [a for a in report["diagnosis"]["actions"] if a["is_write"]]
    assert [w["command"] for w in writes] == [FIX]
    assert "[evidence: L1]" in writes[0]["rationale"]
    top_evidence = report["diagnosis"]["hypotheses"][0]["evidence"]
    assert any(line.startswith("L1 (ok): kubectl get services -n default") for line in top_evidence)


def test_an_address_pointing_at_the_wrong_service_is_sent_back_naming_the_right_one():
    # What deepseek-v4-flash proposed first, every time: CART_ADDR = cart's own Service.
    llm = FakeLLM({"fix": [answer(value="cart:7070"), answer()]})
    outcome = propose(llm)
    assert outcome.action.command == FIX
    reason = llm.prompts[1][1]["rejected"][0]
    assert "cannot reach (redis)" in reason and "service list" in reason


def test_without_a_named_service_an_address_still_may_not_point_at_itself():
    ctx = CTX.model_copy(update={"symptoms": ["cart: log_error (CART_ADDR environment variable not set)"]})
    llm = FakeLLM({"fix": [answer(value="cart:7070"), answer(template="none")]})
    FixProposer(llm, FakeReadExecutor(READS)).propose(hyp(), ctx, [E1], {})
    assert "points cart at itself" in llm.prompts[1][1]["rejected"][0]


def test_m1_signal_lines_are_shown_and_citable_but_never_ground_a_value():
    # S1 carries "failed to connect to redis", but "redis" is not a Service: the value must come from a read.
    llm = FakeLLM({"fix": [answer(value="redis:6379", cited=("S1",)), answer(template="none")]})
    propose(llm)
    sent = llm.prompts[0][1]["evidence"]
    assert sent[-1]["id"] == "S1" and "failed to connect to redis" in sent[-1]["output"]
    assert "appear in no read's output" in llm.prompts[1][1]["rejected"][0]


DB_DEPLOYMENT = (
    '{"spec": {"template": {"spec": {"containers": [{"name": "db"}],'
    ' "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "db-pvc"}}]}}}}'
)
DB_PVC = '{"spec": {"storageClassName": "standard"}, "status": {"capacity": {"storage": "5Gi"}}}'


def test_a_full_volume_gets_no_write_but_the_expansion_for_a_person():
    reads = FakeReadExecutor(
        {
            "kubectl get deployment db -n default -o json": DB_DEPLOYMENT,
            "kubectl get pvc db-pvc -n default -o json": DB_PVC,
        }
    )
    outcome = FixProposer(reads=reads).propose(hyp("storage", "db"), CTX, [], {})
    assert outcome.action is None and outcome.source == "none"
    assert outcome.note.startswith("human_action_required:")
    assert "from 5Gi to 10Gi" in outcome.note
    assert (
        '`kubectl patch pvc db-pvc -n default -p \'{"spec":{"resources":{"requests":{"storage":"10Gi"}}}}\'`'
        in outcome.note
    )
    assert "storage class standard" in outcome.note
    assert [e.id for e in outcome.lookups] == ["L1", "L2"]


def test_a_full_volume_without_a_readable_pvc_still_hands_over_without_guessing_a_name():
    outcome = FixProposer().propose(hyp("storage", "db"), CTX, [], {})
    assert outcome.action is None
    assert "expand the PVC that db mounts" in outcome.note and "kubectl patch" not in outcome.note
