from argus.contracts import DiagnosisResult, GateDecision, SafetyVerdict, SemanticContext
from argus.diagnosis.core.readonly import is_read_only
from argus.diagnosis.ports.fakes import FakeLLM, FakeReadExecutor
from argus.diagnosis.service import blocked_commands, diagnose

# scenario_01 in M1 F2 form: frontend calls cart, and cart is the failing service.
CONTEXT = SemanticContext(
    services=["frontend", "cart"],
    dependencies=[("frontend", "cart")],
    failing_services=["cart"],
    entry_point="frontend",
)
CART_YAML = "kubectl get deployment cart -n default -o yaml"
CART_SUPPORTED = {"H1": "strong-support", "H2": "strong-refute", "H3": "strong-refute"}


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
    context = CONTEXT.model_copy(
        update={
            "anomalies": [
                "cart: log_error (failed to connect to redis: CART_ADDR environment variable not set)"
            ]
        }
    )
    llm = FakeLLM({"score": [{"verdicts": CART_SUPPORTED}]})
    reads = FakeReadExecutor({CART_YAML: "env: CART_ADDR missing"})
    writes = [a for a in diagnose(context, llm=llm, reads=reads).actions if a.is_write]
    assert len(writes) == 1
    assert writes[0].command.startswith("kubectl patch deployment cart -n default -p ")
    assert "CART_ADDR" in writes[0].command


def test_no_llm_no_cluster_still_ranks_cart_first():
    result = diagnose(CONTEXT)
    assert result.hypotheses[0].root_cause.startswith("cart")
    assert all("unavailable" in line for h in result.hypotheses for line in h.evidence)


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
    assert blocked_commands([approved, blocked]) == {CART_YAML}
    assert blocked_commands(None) == set()