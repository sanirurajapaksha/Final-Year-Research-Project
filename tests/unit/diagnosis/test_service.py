from argus.contracts import DiagnosisResult, GateDecision, SafetyVerdict, SemanticContext
from argus.diagnosis.core.config import DiagnosisConfig
from argus.diagnosis.ports.fakes import FakeLLM, FakeReadExecutor
from argus.diagnosis.service import Diagnoser, diagnose

CTX = SemanticContext(services=["frontend", "cart"], failing_services=["frontend"])
FRONTEND_YAML = "kubectl get deployment frontend -n demo -o yaml"
EXAMPLE_A = {"score": [{"verdicts": {"H1": "strong-support", "H2": "strong-refute", "H3": "strong-refute"}}]}


def _example_a():
    reads = FakeReadExecutor({FRONTEND_YAML: "env: CART_ADDR missing"})
    return Diagnoser(DiagnosisConfig(namespace="demo"), FakeLLM(EXAMPLE_A), reads), reads


def test_diagnose_returns_a_diagnosis_result():
    assert isinstance(diagnose(SemanticContext()), DiagnosisResult)


def test_defaults_give_probabilities_that_sum_to_one_with_h0():
    result = diagnose(CTX)
    assert abs(sum(h.probability for h in result.hypotheses) - 1.0) < 1e-9
    assert any(h.root_cause.startswith("H0") for h in result.hypotheses)
    assert result.actions == []


def test_empty_context_gives_h0_with_the_reason():
    result = diagnose(SemanticContext(notes="M1 ingest failed"))
    assert len(result.hypotheses) == 1 and result.hypotheses[0].probability == 1.0
    assert "M1 ingest failed" in result.hypotheses[0].root_cause


def test_example_a_top_hypothesis_cites_its_evidence():
    diagnoser, _ = _example_a()
    top = diagnoser.diagnose(CTX).hypotheses[0]
    assert top.root_cause.startswith("H1: frontend [app-config]") and top.probability >= 0.80
    assert top.evidence[0].startswith(f"E1 strong-support {FRONTEND_YAML}: env: CART_ADDR missing")
    assert diagnoser.report.stop_reason == "confident"


def test_feedback_reuses_the_session_without_rerunning_reads():
    diagnoser, reads = _example_a()
    first = diagnoser.diagnose(CTX)
    verdict = SafetyVerdict(
        command="kubectl delete ns demo", decision=GateDecision.BLOCK, reason="namespace delete"
    )
    again = diagnoser.diagnose(CTX, feedback=[verdict])
    assert again == first and reads.calls == [FRONTEND_YAML]
    assert "mitigation needs a human" in diagnoser.report.report_text
