import pytest


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """M2's unit tests never call the real model, even when the developer's shell has a key set."""
    monkeypatch.delenv("ARGUS_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ARGUS_M2_USE_LLM", raising=False)
