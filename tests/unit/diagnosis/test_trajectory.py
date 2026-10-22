import json

from argus.diagnosis.core.config import preset
from argus.diagnosis.core.models import Candidate, DiagContext
from argus.diagnosis.loop.controller import Controller
from argus.diagnosis.loop.trajectory import run_logged
from argus.diagnosis.ports.fakes import FakeLLM, FakeReadExecutor

CTX = DiagContext(
    namespace="demo", candidates=[Candidate(service="frontend", weight=1.5), Candidate(service="cart")]
)
FRONTEND_DEPLOYMENT = "kubectl get deployment frontend -n demo -o json"
CART_DEPLOYMENT = "kubectl get deployment cart -n demo -o json"
REFUTE_ALL = {"H1": "strong-refute", "H2": "strong-refute", "H3": "strong-refute"}


def _example_b(name: str) -> Controller:
    """Example B: the real fault is in cart, but frontend looks guilty first. Fresh fakes per run."""
    llm = FakeLLM(
        {
            "score": [
                {"verdicts": REFUTE_ALL},
                {
                    "verdicts": {
                        **REFUTE_ALL,
                        "H4": "strong-support",
                        "H5": "strong-refute",
                        "H6": "strong-refute",
                    }
                },
            ]
        }
    )
    reads = FakeReadExecutor(
        {FRONTEND_DEPLOYMENT: "env looks fine", CART_DEPLOYMENT: "env: REDIS_ADDR missing"}
    )
    return Controller(preset(name, namespace="demo"), llm, reads)


def test_every_line_is_json_and_tagged_with_its_run(tmp_path):
    path = tmp_path / "traj.jsonl"
    run_logged(_example_b("ach_rca"), CTX, "B-ach", path)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert {line["run"] for line in lines} == {"B-ach"}
    assert [line["event"] for line in lines][0] == "start" and lines[-1]["event"] == "finish"
    update = next(line for line in lines if line["event"] == "update")
    assert update["command"] == FRONTEND_DEPLOYMENT and update["verdicts"]["H1"] == "strong-refute"


def test_greedy_is_confidently_wrong_where_ach_rca_backtracks(tmp_path):
    path = tmp_path / "compare.jsonl"
    _, greedy = run_logged(_example_b("greedy"), CTX, "B-greedy", path)
    _, full = run_logged(_example_b("ach_rca"), CTX, "B-ach", path)
    # Greedy has one guess and no H0: refuting it still leaves it at 100%, so it "stops" on the wrong service.
    assert greedy["top_label"].startswith("frontend") and greedy["stop_reason"] == "confident"
    # The full method notices H0 taking over, backtracks once and lands on cart.
    assert full["top_label"].startswith("cart") and full["rehypothesized"] == 1
    assert len(path.read_text().splitlines()) > 4


def test_a_rules_only_run_logs_no_model_and_counts_sources(tmp_path):
    path = tmp_path / "rules.jsonl"
    _, finish = run_logged(Controller(preset("ach_rca", namespace="demo")), CTX, "rules", path)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    start = lines[0]
    assert start["model"] is None and set(start["prompt_versions"]) == {"score", "draft", "fix", "report"}
    assert not [line for line in lines if line["event"] == "llm_call"]
    assert set(finish["sources"]) == {"rules"}  # no reads succeed, so it backtracks: every round from rules


def test_every_llm_call_is_logged_with_its_status_and_a_prompt_hash(monkeypatch, tmp_path):
    from argus.diagnosis.ports import openrouter
    from argus.diagnosis.ports.openrouter import OpenRouterLLM

    replies = iter(['{"hypotheses": []}', '{"verdicts": "bad"}'])

    def fake(prompt, schema, model, timeout_s, max_tokens, reasoning=None):
        return next(replies, '{"verdicts": []}'), {"prompt_tokens": 50, "completion_tokens": 7}

    monkeypatch.setattr(openrouter, "complete_json", fake)
    reads = FakeReadExecutor({FRONTEND_DEPLOYMENT: "env looks fine"})
    controller = Controller(
        preset("ach_rca", namespace="demo", max_rehyp=0), OpenRouterLLM("test/model"), reads
    )
    path = tmp_path / "llm.jsonl"
    run_logged(controller, CTX, "llm", path)

    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines[0]["model"] == "test/model"
    calls = [line for line in lines if line["event"] == "llm_call"]
    assert [(c["task"], c["status"]) for c in calls][:2] == [("draft", "ok"), ("score", "invalid")]
    assert all(len(c["prompt_sha256"]) == 16 and c["prompt_chars"] > 0 for c in calls)
    assert calls[0]["usage"] == {"prompt_tokens": 50, "completion_tokens": 7}
    assert lines[-1]["sources"] == {"rules": 3}  # the LLM drafted nothing usable, so the rules did


def test_a_second_run_with_the_same_llm_logs_only_its_own_calls(monkeypatch, tmp_path):
    from argus.diagnosis.ports import openrouter
    from argus.diagnosis.ports.openrouter import OpenRouterLLM

    monkeypatch.setattr(openrouter, "complete_json", lambda *a, **k: ('{"hypotheses": []}', {}))
    llm = OpenRouterLLM("test/model")
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    run_logged(Controller(preset("ach_rca", namespace="demo"), llm), CTX, "a", first)
    run_logged(Controller(preset("ach_rca", namespace="demo"), llm), CTX, "b", second)
    count = lambda p: sum(json.loads(x)["event"] == "llm_call" for x in p.read_text().splitlines())  # noqa: E731
    assert count(first) == count(second) == len(llm.calls) // 2
