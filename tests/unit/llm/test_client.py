"""The shared LLM client, with the network replaced by a fake (no real API calls in tests)."""

import io
import json
import urllib.request

import pytest

from argus.llm import client
from argus.llm.client import LLMError, complete_json

SCHEMA = {
    "type": "object",
    "properties": {"x": {"type": "integer"}},
    "required": ["x"],
    "additionalProperties": False,
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_sends_the_model_and_schema_and_returns_the_text(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout):
        sent["url"] = request.full_url
        sent["auth"] = request.get_header("Authorization")
        sent["body"] = json.loads(request.data)
        reply = {"choices": [{"message": {"content": '{"x": 1}'}}], "usage": {"total_tokens": 42}}
        return FakeResponse(json.dumps(reply).encode("utf-8"))

    monkeypatch.setenv("ARGUS_LLM_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    text, usage = complete_json("say x", SCHEMA, "some/model")

    assert text == '{"x": 1}'
    assert usage == {"total_tokens": 42}
    assert sent["url"] == client.OPENROUTER_URL
    assert sent["auth"] == "Bearer test-key"
    assert sent["body"]["model"] == "some/model"
    assert sent["body"]["response_format"]["json_schema"]["schema"] == SCHEMA


def test_missing_key_or_model_is_an_error(monkeypatch):
    monkeypatch.delenv("ARGUS_LLM_API_KEY", raising=False)
    with pytest.raises(LLMError, match="ARGUS_LLM_API_KEY"):
        complete_json("p", SCHEMA, "some/model")
    monkeypatch.setenv("ARGUS_LLM_API_KEY", "test-key")
    with pytest.raises(LLMError, match="no model"):
        complete_json("p", SCHEMA, "")


def test_network_errors_and_odd_replies_are_errors(monkeypatch):
    monkeypatch.setenv("ARGUS_LLM_API_KEY", "test-key")

    def offline(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(LLMError, match="TimeoutError"):
        complete_json("p", SCHEMA, "some/model")

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: FakeResponse(b'{"error": "x"}'))
    with pytest.raises(LLMError, match="unexpected reply"):
        complete_json("p", SCHEMA, "some/model")
