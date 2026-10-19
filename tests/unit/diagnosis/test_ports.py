import pytest
from pydantic import ValidationError

from argus.diagnosis.core.models import HypothesisSpec
from argus.diagnosis.ports.base import LLMUnavailable, ReadResult, guarded_run
from argus.diagnosis.ports.fakes import FakeLLM, FakeReadExecutor, NoLLM, NullReadExecutor

GOOD = {
    "component": "cart",
    "layer": "app-config",
    "fault": "CART_ADDR missing",
    "test": "kubectl get deploy cart -o yaml",
}


def test_guard_blocks_writes_before_the_executor():
    reads = FakeReadExecutor({})
    result = guarded_run(reads, "kubectl delete pod cart-1")
    assert not result.ok and result.output.startswith("blocked")
    assert reads.calls == []  # never reached the executor


def test_guard_passes_reads():
    reads = FakeReadExecutor({"kubectl get pods": "cart-1 Running"})
    assert guarded_run(reads, "kubectl get pods") == ReadResult(output="cart-1 Running", ok=True)


def test_guard_turns_an_executor_crash_into_a_failed_read():
    class Broken:
        def run(self, command):
            raise TimeoutError("slow")

    assert not guarded_run(Broken(), "kubectl get pods").ok


def test_null_executor_and_unknown_command_fail():
    assert not NullReadExecutor().run("kubectl get pods").ok
    assert not FakeReadExecutor({}).run("kubectl get pods").ok


def test_no_llm_raises_unavailable():
    with pytest.raises(LLMUnavailable):
        NoLLM().structured("generate", HypothesisSpec)


def test_fake_llm_answers_in_order_then_runs_out():
    llm = FakeLLM({"generate": [GOOD]})
    hypothesis = llm.structured("generate", HypothesisSpec, context="x")
    assert hypothesis.component == "cart" and llm.usage["calls"] == 1
    assert llm.prompts == [("generate", {"context": "x"})]
    with pytest.raises(LLMUnavailable):
        llm.structured("generate", HypothesisSpec)


def test_fake_llm_bad_answer_fails_validation():
    llm = FakeLLM({"generate": [{"component": "cart"}]})  # missing fields
    with pytest.raises(ValidationError):
        llm.structured("generate", HypothesisSpec)
