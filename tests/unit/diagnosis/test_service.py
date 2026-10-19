from argus.contracts import DiagnosisResult, GateDecision, SafetyVerdict, SemanticContext
from argus.diagnosis.core.readonly import is_read_only
from argus.diagnosis.ports.fakes import FakeLLM, FakeReadExecutor
from argus.diagnosis.service import blocked_verdicts, diagnose, diagnose_report

# scenario_01 in M1 F2 form: frontend calls cart, and cart is the failing service.
CONTEXT = SemanticContext(
    services=["frontend", "cart"],
    dependencies=[("frontend", "cart")],
    failing_services=["cart"],
    entry_point="frontend",
)
CART_YAML = "kubectl get deployment cart -n default -o yaml"
CART_SUPPORTED = {"H1": "strong-support", "H2": "strong-refute", "H3": "strong-refute"}
CART_LOG = "cart: log_error (failed to connect to redis: CART_ADDR environment variable not set)"


def test_diagnose_returns_a_diagnosis_result():
    assert isinstance(diagnose(SemanticContext()), DiagnosisResult)


def test_top_hypothesis_is_cart_missing_address():
    llm = FakeLLM({"score": [{"verdicts": CART_SUPPORTED}]})
    reads = FakeReadExecutor({CART_YAML: "env: CART_ADDR missing"})
    result = diagnose(CONTEXT, llm=llm, reads=reads)
    top = result.hypotheses[0]
    assert top.root_cause.startswith("cart [app-config]")
    assert top.probability >= 0.80
    assert top.evidence == [f"E1 (ok): {CART_YAML} -> env: CART_ADDR missing"]


def test_hypotheses_are_ranked_best_first():
    llm = FakeLLM({"score": [{"verdicts": CART_SUPPORTED}]})
    reads = FakeReadExecutor({CART_YAML: "env: CART_ADDR missing"})
    probabilities = [h.probability for h in diagnose(CONTEXT, llm=llm, reads=reads).hypotheses]
    assert probabilities == sorted(probabilities, reverse=True)


def test_read_action_checks_the_top_hypothesis():
    llm = FakeLLM({"score": [{"verdicts": CART_SUPPORTED}]})
    reads = FakeReadExecutor({CART_YAML: "env: CART_ADDR missing"})
    reads_proposed = [a for a in diagnose(CONTEXT, llm=llm, reads=reads).actions if not a.is_write]
    assert [a.command for a in reads_proposed] == [CART_YAML]
    assert reads_proposed[0].target_namespace == "default"
    assert is_read_only(reads_proposed[0].command)


def test_top_hypothesis_gets_a_write_action_for_m3():
    context = CONTEXT.model_copy(update={"anomalies": [CART_LOG]})
    llm = FakeLLM({"score": [{"verdicts": CART_SUPPORTED}]})
    reads = FakeReadExecutor({CART_YAML: "env: CART_ADDR missing"})
    writes = [a for a in diagnose(context, llm=llm, reads=reads).actions if a.is_write]
    assert len(writes) == 1
    assert writes[0].command.startswith("kubectl patch deployment cart -n default -p ")
    assert "CART_ADDR" in writes[0].command


def test_no_llm_no_cluster_still_ranks_cart_first():
    result = diagnose(CONTEXT)
    assert result.hypotheses[0].root_cause.startswith("cart")
    for hypothesis in result.hypotheses:
        for line in hypothesis.evidence:
            assert "unavailable" in line or line.startswith("No write:")


def test_no_write_when_no_read_confirmed_the_top_hypothesis():
    # M4's default run_once(batch): no reads at all, so the loop ends unsure. Its patch must not
    # reach M3, which could approve a config change M2 never confirmed.
    context = CONTEXT.model_copy(update={"anomalies": [CART_LOG]})
    report = diagnose_report(context)
    assert report["low_confidence"]
    actions = diagnose(context).actions
    assert [a for a in actions if a.is_write] == []
    assert [a.command for a in actions] == [CART_YAML]  # the read that would confirm it stays
    reason = diagnose(context).hypotheses[0].evidence[-1]
    assert reason.startswith("No write: the reads did not confirm this hypothesis")
    assert report["stop_reason"] in reason


def test_no_write_when_none_of_these_wins():
    # Every read refutes its hypothesis, so H0 ("none of these") ends on top: no fix is proposed.
    context = CONTEXT.model_copy(update={"anomalies": [CART_LOG]})
    refuted = {"H1": "strong-refute", "H2": "strong-refute", "H3": "strong-refute"}
    llm = FakeLLM({"score": [{"verdicts": refuted}] * 10})
    reads = FakeReadExecutor({CART_YAML: "a healthy deployment"})
    report = diagnose_report(context, llm=llm, reads=reads)
    assert report["stop_reason"] != "confident"
    assert [a for a in diagnose(context, llm=llm, reads=reads).actions if a.is_write] == []


def test_empty_context_gives_no_hypotheses_and_no_actions():
    result = diagnose(SemanticContext(notes="no anomalies"))
    assert result.hypotheses == []
    assert result.actions == []


def test_blocked_command_is_never_proposed_again():
    blocked = SafetyVerdict(command=CART_YAML, decision=GateDecision.BLOCK, reason="test block")
    result = diagnose(CONTEXT, feedback=[blocked])
    assert CART_YAML not in [a.command for a in result.actions]


def test_only_block_verdicts_count_as_blocked():
    approved = SafetyVerdict(
        command="kubectl get pods -n default", decision=GateDecision.APPROVE, reason="ok"
    )
    blocked = SafetyVerdict(command=CART_YAML, decision=GateDecision.BLOCK, reason="test block")
    assert blocked_verdicts([approved, blocked]) == {CART_YAML: blocked}
    assert blocked_verdicts(None) == {}


def test_blocked_fix_is_dropped_with_m3s_reason():
    context = CONTEXT.model_copy(update={"anomalies": [CART_LOG]})
    llm = FakeLLM({"score": [{"verdicts": CART_SUPPORTED}] * 2})
    reads = FakeReadExecutor({CART_YAML: "env: CART_ADDR missing"})
    fix = next(a for a in diagnose(context, llm=llm, reads=reads).actions if a.is_write)
    llm = FakeLLM({"score": [{"verdicts": CART_SUPPORTED}] * 2})  # a fresh copy: answers are used up
    verdict = SafetyVerdict(
        command=fix.command,
        decision=GateDecision.BLOCK,
        reason="min_available violated",
        counterexample={"cart.available": 0},
    )
    result = diagnose(context, feedback=[verdict], llm=llm, reads=reads)
    assert [a for a in result.actions if a.is_write] == []
    reason = result.hypotheses[0].evidence[-1]
    assert reason.startswith("M3 blocked the fix")
    assert "min_available violated" in reason and '"cart.available": 0' in reason
    assert "proposes no write" in reason


def test_report_matches_the_diagnosis():
    llm = FakeLLM({"score": [{"verdicts": CART_SUPPORTED}]})
    reads = FakeReadExecutor({CART_YAML: "env: CART_ADDR missing"})
    report = diagnose_report(CONTEXT, llm=llm, reads=reads)
    assert report["stop_reason"] == "confident"
    assert report["hypotheses"][0]["id"] == "H1"
    assert report["reads"][0]["command"] == CART_YAML
    assert [r["event"] for r in report["belief_rounds"]] == ["init", "update"]
    assert report["diagnosis"]["hypotheses"][0]["root_cause"].startswith("cart [app-config]")
