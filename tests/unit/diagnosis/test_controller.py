from argus.diagnosis.core.config import DiagnosisConfig
from argus.diagnosis.core.models import Candidate, DiagContext
from argus.diagnosis.core.readonly import is_read_only
from argus.diagnosis.loop.controller import Controller
from argus.diagnosis.ports.fakes import FakeLLM, FakeReadExecutor

CTX = DiagContext(namespace="demo", candidates=[Candidate(service="frontend", weight=1.5), Candidate(service="cart")])
FRONTEND_YAML = "kubectl get deployment frontend -n demo -o yaml"
CART_YAML = "kubectl get deployment cart -n demo -o yaml"
REFUTE_ALL = {"H1": "strong-refute", "H2": "strong-refute", "H3": "strong-refute"}


def test_example_a_stops_on_h1_after_one_read():
    llm = FakeLLM({"score": [{"verdicts": {"H1": "strong-support", "H2": "strong-refute", "H3": "strong-refute"}}]})
    reads = FakeReadExecutor({FRONTEND_YAML: "env: CART_ADDR missing"})
    result = Controller(llm=llm, reads=reads).run(CTX)
    assert result.report.stop_reason == "confident"
    top, p = result.belief.ranked()[0]
    assert top == "H1" and p >= 0.80
    assert reads.calls == [FRONTEND_YAML]


def test_example_b_backtracks_through_h0_to_h4():
    llm = FakeLLM({"score": [
        {"verdicts": REFUTE_ALL},
        {"verdicts": {**REFUTE_ALL, "H4": "strong-support", "H5": "strong-refute", "H6": "strong-refute"}},
    ]})
    reads = FakeReadExecutor({FRONTEND_YAML: "env looks fine", CART_YAML: "env: REDIS_ADDR missing"})
    result = Controller(llm=llm, reads=reads).run(CTX)
    assert [h["event"] for h in result.belief.history].count("rehypothesize") == 1
    top, p = result.belief.ranked()[0]
    assert top == "H4" and result.hypotheses["H4"].component == "cart"
    # One strong-support after a backtrack reaches ~0.77: H4 leads, but below theta, so it's flagged.
    assert 0.7 < p < 0.8 and result.report.low_confidence
    assert reads.calls == [FRONTEND_YAML, CART_YAML]


def test_no_llm_no_cluster_ends_low_confidence_without_crashing():
    result = Controller().run(CTX)
    assert result.report.low_confidence
    assert all(is_read_only(e.command) for e in result.evidence)


def test_read_budget_is_respected():
    result = Controller(config=DiagnosisConfig(max_reads=2)).run(CTX)
    assert len(result.evidence) <= 2 and result.report.stop_reason == "budget"


def test_empty_context_reports_why():
    result = Controller().run(DiagContext(namespace="demo", notes="M1 ingest failed"))
    assert result.report.stop_reason == "no hypotheses: M1 ingest failed"