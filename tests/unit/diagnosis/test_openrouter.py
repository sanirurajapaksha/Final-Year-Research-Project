import json
from typing import Literal

import pytest
from pydantic import BaseModel

from argus.contracts import SemanticContext
from argus.diagnosis.ports import openrouter
from argus.diagnosis.ports.base import LLMUnavailable
from argus.diagnosis.ports.openrouter import OpenRouterLLM, llm_from_env, strict_schema
from argus.diagnosis.prompts import PROMPTS, Template, wrap
from argus.diagnosis.service import diagnose_report
from argus.llm.client import LLMError

CONTEXT = SemanticContext(failing_services=["cart"], dependencies=[("frontend", "cart")])


class Item(BaseModel):
    id: str
    verdict: Literal["strong-support", "neutral"] = "neutral"


class Answer(BaseModel):
    items: list[Item] = []
    note: str = ""


class Loose(BaseModel):
    verdicts: dict[str, str] = {}


@pytest.fixture
def echo_task(monkeypatch):
    """A test-only template, so the adapter has something to render."""
    monkeypatch.setitem(PROMPTS, "echo", Template("echo", "echo-v1", lambda text: wrap("signals", text)))


def fake_complete_json(reply, usage=None, seen=None):
    """Stands in for argus.llm.client.complete_json: no network, no key."""

    def call(prompt, schema, model, timeout_s, max_tokens, reasoning=None):
        if seen is not None:
            seen.update(prompt=prompt, schema=schema, model=model, timeout_s=timeout_s, max_tokens=max_tokens)
            seen["reasoning"] = reasoning
        if isinstance(reply, Exception):
            raise reply
        return reply, usage or {"prompt_tokens": 12, "completion_tokens": 5}

    return call


# ---------- strict_schema ----------


def test_strict_schema_closes_every_object_and_requires_every_field():
    schema = strict_schema(Answer)
    assert schema["additionalProperties"] is False and schema["required"] == ["items", "note"]
    item = schema["$defs"]["Item"]
    assert item["additionalProperties"] is False and item["required"] == ["id", "verdict"]
    assert "default" not in json.dumps(schema)


def test_strict_schema_refuses_a_free_form_dict():
    with pytest.raises(ValueError, match="free-form"):
        strict_schema(Loose)


def test_strict_schema_does_not_change_the_models_own_schema():
    strict_schema(Answer)
    assert "default" in json.dumps(Answer.model_json_schema())


# ---------- OpenRouterLLM ----------


def test_good_answer_is_validated_and_tokens_counted(monkeypatch, echo_task):
    seen = {}
    reply = '{"items": [{"id": "H1", "verdict": "strong-support"}], "note": ""}'
    monkeypatch.setattr(openrouter, "complete_json", fake_complete_json(reply, seen=seen))
    llm = OpenRouterLLM("deepseek/test-model")

    answer = llm.structured("echo", Answer, text="cart: CART_ADDR not set")

    assert answer.items[0].verdict == "strong-support"
    assert llm.usage == {"calls": 1, "failed": 0, "prompt_tokens": 12, "completion_tokens": 5}
    assert seen["model"] == "deepseek/test-model"
    assert seen["max_tokens"] == 1000 and seen["timeout_s"] == 30.0
    assert "<signals>" in seen["prompt"] and seen["schema"]["additionalProperties"] is False
    assert llm.calls[0]["prompt_version"] == "echo-v1" and llm.calls[0]["reply"] == reply


def test_client_error_becomes_llm_unavailable(monkeypatch, echo_task):
    monkeypatch.setattr(openrouter, "complete_json", fake_complete_json(LLMError("no answer within 30 s")))
    llm = OpenRouterLLM("m")
    with pytest.raises(LLMUnavailable):
        llm.structured("echo", Answer, text="x")
    assert llm.usage["failed"] == 1 and llm.calls[0]["reply"].startswith("error:")


def test_reply_that_does_not_validate_is_a_value_error(monkeypatch, echo_task):
    bad = '{"items": [{"id": "H1", "verdict": "maybe"}], "note": ""}'
    monkeypatch.setattr(openrouter, "complete_json", fake_complete_json(bad))
    llm = OpenRouterLLM("m")
    with pytest.raises(ValueError):
        llm.structured("echo", Answer, text="x")
    assert llm.usage["failed"] == 1


def test_task_without_a_template_is_unavailable_and_makes_no_call(monkeypatch):
    monkeypatch.setattr(openrouter, "complete_json", fake_complete_json(AssertionError("must not be called")))
    llm = OpenRouterLLM("m")
    with pytest.raises(LLMUnavailable):
        llm.structured("no-such-task", Answer)
    assert llm.usage["calls"] == 0


# ---------- choosing the LLM ----------


def test_llm_from_env_needs_both_key_and_model(monkeypatch):
    assert llm_from_env("some/model") is None  # conftest removed the key
    monkeypatch.setenv("ARGUS_LLM_API_KEY", "test-key")
    assert llm_from_env("") is None
    assert isinstance(llm_from_env("some/model"), OpenRouterLLM)


def test_diagnose_without_a_key_runs_on_rules():
    assert diagnose_report(CONTEXT)["hypotheses"]  # rules drafted them, nothing touched the network


def test_a_key_alone_does_not_turn_the_llm_on(monkeypatch):
    # Review on #41: the key and model are shared with M3, so having them set must not make M2 paid.
    monkeypatch.setenv("ARGUS_LLM_API_KEY", "test-key")
    monkeypatch.setenv("ARGUS_LLM_MODEL", "deepseek/test-model")
    monkeypatch.setattr("argus.diagnosis.service.llm_from_env", lambda model: pytest.fail("LLM was built"))
    monkeypatch.setattr(openrouter, "complete_json", fake_complete_json(AssertionError("must not be called")))
    assert diagnose_report(CONTEXT)["hypotheses"]  # rules, as before this PR


@pytest.mark.parametrize("value", ["0", "", "no", "false"])
def test_the_opt_in_flag_must_say_yes(monkeypatch, value):
    monkeypatch.setenv("ARGUS_LLM_API_KEY", "test-key")
    monkeypatch.setenv("ARGUS_LLM_MODEL", "deepseek/test-model")
    monkeypatch.setenv("ARGUS_M2_USE_LLM", value)
    monkeypatch.setattr("argus.diagnosis.service.llm_from_env", lambda model: pytest.fail("LLM was built"))
    diagnose_report(CONTEXT)


def test_diagnose_with_the_opt_in_builds_the_teams_model_and_still_falls_back(monkeypatch):
    monkeypatch.setenv("ARGUS_LLM_API_KEY", "test-key")
    monkeypatch.setenv("ARGUS_LLM_MODEL", "deepseek/test-model")
    monkeypatch.setenv("ARGUS_M2_USE_LLM", "1")
    built = []

    def spy(model):
        llm = llm_from_env(model)
        built.append(llm)
        return llm

    monkeypatch.setattr("argus.diagnosis.service.llm_from_env", spy)
    monkeypatch.setattr(
        openrouter,
        "complete_json",
        fake_complete_json(LLMError("offline")),
    )
    report = diagnose_report(CONTEXT)

    assert [llm.model for llm in built] == ["deepseek/test-model"]
    assert report["hypotheses"]  # the draft call failed, so the rules drafted instead
    assert {c["task"] for c in built[0].calls} == {"draft", "report"}  # each try failed and fell back
    assert built[0].usage["failed"] == built[0].usage["calls"] >= 1


def test_each_task_sends_its_own_token_budget_and_reasoning_setting(monkeypatch):
    from argus.diagnosis.loop.controller import ScoreAnswer
    from argus.diagnosis.loop.llm_generator import DraftAnswer

    seen = {}
    monkeypatch.setattr(openrouter, "complete_json", fake_complete_json('{"verdicts": []}', seen=seen))
    llm = OpenRouterLLM("m")
    llm.structured("score", ScoreAnswer, command="kubectl get pods", output="x", hypotheses={})
    assert (seen["max_tokens"], seen["timeout_s"], seen["reasoning"]) == (3000, 60.0, {"effort": "low"})

    monkeypatch.setattr(openrouter, "complete_json", fake_complete_json('{"hypotheses": []}', seen=seen))
    llm.structured(
        "draft",
        DraftAnswer,
        candidates=[],
        failing_path=[],
        signals=[],
        pod_status={},
        refuted=[],
        k=3,
        namespace="ns",
    )
    assert (seen["max_tokens"], seen["timeout_s"], seen["reasoning"]) == (1500, 30.0, {"enabled": False})


def test_an_empty_reply_is_unavailable_not_a_crash(monkeypatch, echo_task):
    # What deepseek-v4-flash sent when it thought until the token budget ran out: content None.
    monkeypatch.setattr(openrouter, "complete_json", fake_complete_json(None))
    llm = OpenRouterLLM("m")
    with pytest.raises(LLMUnavailable, match="empty reply"):
        llm.structured("echo", Answer, text="x")
    assert llm.usage["failed"] == 1
