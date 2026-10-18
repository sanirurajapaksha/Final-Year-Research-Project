import pytest

from argus.orchestration.fake_models import FakeStep, ScriptedAdapter
from argus.orchestration.model_dispatch import AdapterReply
from argus.orchestration.router import CandidateEstimate, RoutingTask

TASK = RoutingTask(task_id="parse", task_kind="telemetry_parsing", min_quality=1)
CANDIDATE = CandidateEstimate(
    task_id="parse", model_id="fake", layer="low_cost", estimated_cost_units=1, quality=1
)


def test_script_is_copied_and_consumed_in_order():
    original = {"text": ["first"]}
    steps = [FakeStep(original), FakeStep({"text": ["second"]})]
    adapter = ScriptedAdapter({("parse", "fake"): steps})
    original["text"].append("changed")
    steps.clear()
    first = adapter.call(TASK, CANDIDATE, "exact\tprompt\n", timeout_ms=5)
    assert first.output == {"text": ["first"]}
    assert adapter.call(TASK, CANDIDATE, "second", timeout_ms=5).output == {"text": ["second"]}
    with pytest.raises(RuntimeError, match="no remaining"):
        adapter.call(TASK, CANDIDATE, "third", timeout_ms=5)
    assert adapter.calls[0].prompt == "exact\tprompt\n"
    assert len(adapter.calls) == 3


def test_exact_deadline_success_then_simulated_timeout_and_error():
    adapter = ScriptedAdapter(
        {
            ("parse", "fake"): [
                FakeStep("on time", elapsed_ms=5),
                FakeStep("too late", elapsed_ms=6),
                FakeStep(error=RuntimeError("model error")),
            ]
        }
    )
    assert adapter.call(TASK, CANDIDATE, "prompt", timeout_ms=5) == AdapterReply("on time", 5)
    with pytest.raises(TimeoutError):
        adapter.call(TASK, CANDIDATE, "prompt", timeout_ms=5)
    with pytest.raises(RuntimeError, match="model error"):
        adapter.call(TASK, CANDIDATE, "prompt", timeout_ms=5)


@pytest.mark.parametrize("value", [-1, True, 0.5])
def test_invalid_reply_and_step_duration_rejected(value):
    with pytest.raises(ValueError):
        FakeStep(elapsed_ms=value)
    with pytest.raises(ValueError):
        AdapterReply("result", value)


def test_ambiguous_or_invalid_fake_error_rejected():
    with pytest.raises(ValueError):
        FakeStep(output="result", error=RuntimeError("error"))
    with pytest.raises(ValueError):
        FakeStep(error="not an exception")


@pytest.mark.parametrize("timeout", [0, True, -1])
def test_bad_call_parameters_do_not_consume_a_script(timeout):
    adapter = ScriptedAdapter({("parse", "fake"): [FakeStep("ok")]})
    with pytest.raises(ValueError):
        adapter.call(TASK, CANDIDATE, "prompt", timeout_ms=timeout)
    assert adapter.calls == ()
    assert adapter.call(TASK, CANDIDATE, "prompt", timeout_ms=1).output == "ok"


def test_wrong_task_candidate_does_not_consume_a_script():
    adapter = ScriptedAdapter({("parse", "fake"): [FakeStep("ok")]})
    other = RoutingTask(task_id="other", task_kind="telemetry_parsing", min_quality=1)
    with pytest.raises(ValueError):
        adapter.call(other, CANDIDATE, "prompt", timeout_ms=1)
    assert adapter.calls == ()
