import json

from argus.diagnosis.core.config import preset
from argus.diagnosis.core.models import Candidate, DiagContext
from argus.diagnosis.loop.controller import Controller
from argus.diagnosis.loop.trajectory import run_logged
from argus.diagnosis.ports.fakes import FakeLLM, FakeReadExecutor

CTX = DiagContext(namespace="demo", candidates=[Candidate(service="frontend", weight=1.5), Candidate(service="cart")])
FRONTEND_YAML = "kubectl get deployment frontend -n demo -o yaml"
CART_YAML = "kubectl get deployment cart -n demo -o yaml"
REFUTE_ALL = {"H1": "strong-refute", "H2": "strong-refute", "H3": "strong-refute"}


def _example_b(name: str) -> Controller:
    """Example B: the real fault is in cart, but frontend looks guilty first. Fresh fakes per run."""
    llm = FakeLLM({"score": [
        {"verdicts": REFUTE_ALL},
        {"verdicts": {**REFUTE_ALL, "H4": "strong-support", "H5": "strong-refute", "H6": "strong-refute"}},
    ]})
    reads = FakeReadExecutor({FRONTEND_YAML: "env looks fine", CART_YAML: "env: REDIS_ADDR missing"})
    return Controller(preset(name, namespace="demo"), llm, reads)


def test_every_line_is_json_and_tagged_with_its_run(tmp_path):
    path = tmp_path / "traj.jsonl"
    run_logged(_example_b("ach_rca"), CTX, "B-ach", path)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert {line["run"] for line in lines} == {"B-ach"}
    assert [line["event"] for line in lines][0] == "start" and lines[-1]["event"] == "finish"
    update = next(line for line in lines if line["event"] == "update")
    assert update["command"] == FRONTEND_YAML and update["verdicts"]["H1"] == "strong-refute"


def test_greedy_is_confidently_wrong_where_ach_rca_backtracks(tmp_path):
    path = tmp_path / "compare.jsonl"
    _, greedy = run_logged(_example_b("greedy"), CTX, "B-greedy", path)
    _, full = run_logged(_example_b("ach_rca"), CTX, "B-ach", path)
    # Greedy has one guess and no H0: refuting it still leaves it at 100%, so it "stops" on the wrong service.
    assert greedy["top_label"].startswith("frontend") and greedy["stop_reason"] == "confident"
    # The full method notices H0 taking over, backtracks once and lands on cart.
    assert full["top_label"].startswith("cart") and full["rehypothesized"] == 1
    assert len(path.read_text().splitlines()) > 4