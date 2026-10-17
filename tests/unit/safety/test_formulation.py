"""The Formulation Agent with the LLM replaced by canned answers (no network in tests)."""

import json

import pytest

from argus.llm.client import LLMError
from argus.safety import formulation
from argus.safety.formulation import FormulationError, formulate, handles
from argus.safety.parser import Action, ParseError

REPLICAS_1 = 'kubectl patch deployment geo -n hr -p \'{"spec":{"replicas":1}}\''
TEMPLATE = 'kubectl patch deploy/user -n hr -p \'{"spec":{"template":{"metadata":{"labels":{"v":"2"}}}}}\''
LABEL = 'kubectl patch deployment frontend -n hr --type=merge -p \'{"metadata":{"labels":{"team":"sre"}}}\''


def llm_says(monkeypatch, answer: dict) -> list:
    """Make the LLM return `answer`; return the list of prompts it was sent."""
    prompts = []

    def fake_complete_json(prompt, schema, model, timeout_s):
        prompts.append(prompt)
        return json.dumps(answer), {"total_tokens": 10}

    monkeypatch.setattr(formulation, "complete_json", fake_complete_json)
    return prompts


def ir(name: str, effect: str, replicas: int = 0, namespace: str = "hr") -> dict:
    return {
        "kind": "deployment",
        "name": name,
        "namespace": namespace,
        "effect": effect,
        "replicas": replicas,
    }


def test_handles_only_patch():
    assert handles(REPLICAS_1)
    assert not handles("kubectl scale deployment geo --replicas=1 -n hr")


def test_set_replicas_becomes_a_scale(monkeypatch):
    llm_says(monkeypatch, ir("geo", "set_replicas", 1))
    assert formulate(REPLICAS_1, "m", "") == Action("scale", "deployment", "geo", "hr", {"replicas": 1})


def test_template_change_becomes_a_rolling_restart(monkeypatch):
    llm_says(monkeypatch, ir("user", "pod_template_change"))
    assert formulate(TEMPLATE, "m", "") == Action("rollout-restart", "deployment", "user", "hr")


def test_label_patch_becomes_a_metadata_change(monkeypatch):
    llm_says(monkeypatch, ir("frontend", "metadata_only"))
    assert formulate(LABEL, "m", "") == Action("patch-metadata", "deployment", "frontend", "hr")


@pytest.mark.parametrize(
    ("answer", "reason_part"),
    [
        (ir("geo", "metadata_only"), "LLM says 'metadata_only'"),  # missed the replicas change
        (ir("geo", "set_replicas", 5), "replicas=5"),  # wrong number
        (ir("frontend", "set_replicas", 1), "different target"),  # wrong name
        (ir("geo", "set_replicas", 1, namespace="kube-system"), "different target"),  # wrong namespace
        (ir("geo", "unknown"), "LLM says 'unknown'"),
    ],
)
def test_disagreeing_llm_answers_block(monkeypatch, answer, reason_part):
    llm_says(monkeypatch, answer)
    with pytest.raises(FormulationError, match=reason_part):
        formulate(REPLICAS_1, "m", "")


def test_an_answer_outside_the_schema_blocks(monkeypatch):
    llm_says(monkeypatch, {"kind": "deployment", "name": "geo"})
    with pytest.raises(FormulationError, match="schema"):
        formulate(REPLICAS_1, "m", "")


def test_an_llm_failure_blocks(monkeypatch):
    def offline(prompt, schema, model, timeout_s):
        raise LLMError("TimeoutError: timed out")

    monkeypatch.setattr(formulation, "complete_json", offline)
    with pytest.raises(FormulationError, match="LLM: TimeoutError"):
        formulate(REPLICAS_1, "m", "")


def test_two_changes_in_one_patch_block(monkeypatch):
    both = 'kubectl patch deployment geo -n hr -p \'{"spec":{"replicas":1,"template":{}}}\''
    llm_says(monkeypatch, ir("geo", "unknown"))
    with pytest.raises(FormulationError, match="unknown effect"):
        formulate(both, "m", "")


@pytest.mark.parametrize(
    ("command", "error"),
    [
        ("kubectl patch service frontend -n hr -p '{\"spec\":{}}'", FormulationError),  # not a deployment
        ('kubectl patch deployment geo -p \'{"spec":{"replicas":1}}\'', ParseError),  # no -n
        ("kubectl patch deployment geo -n hr --type=json -p '[]'", FormulationError),  # JSON patch
        ("kubectl patch deployment geo -n hr --dry-run=server -p '{}'", FormulationError),  # unknown flag
    ],
)
def test_commands_v0_doesnt_read_block_before_asking_the_llm(monkeypatch, command, error):
    prompts = llm_says(monkeypatch, ir("geo", "set_replicas", 1))
    with pytest.raises(error):
        formulate(command, "m", "")
    assert prompts == []


def test_every_raw_answer_is_logged(monkeypatch, tmp_path):
    llm_says(monkeypatch, ir("geo", "set_replicas", 1))
    log = tmp_path / "llm.jsonl"
    formulate(REPLICAS_1, "some/model", str(log))
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert entry["command"] == REPLICAS_1
    assert entry["model"] == "some/model"
    assert json.loads(entry["raw"])["effect"] == "set_replicas"
    assert entry["usage"] == {"total_tokens": 10}
