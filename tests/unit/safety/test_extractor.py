import json
import subprocess
from pathlib import Path

import pytest

from argus.safety.extractor import extract, is_read_only, live_kubectl, saved_output

KUBECTL_OUTPUT = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "m3" / "kubectl"


def deployment(name: str, facts: dict) -> dict:
    for item in facts["deployments"]:
        if item["name"] == name:
            return item
    raise KeyError(name)


def test_facts_from_saved_kubectl_output():
    snapshot = extract("hotel-reservation", saved_output(KUBECTL_OUTPUT))
    assert deployment("geo", snapshot) == {
        "namespace": "hotel-reservation",
        "name": "geo",
        "replicas": 3,
        "min_replicas": 2,
        "max_unavailable": 1,
        "max_surge": 1,
    }
    assert {"namespace": "hotel-reservation", "name": "geo-pvc", "in_use": True} in snapshot["pvcs"]
    assert {"namespace": "hotel-reservation", "name": "old-pvc", "in_use": False} in snapshot["pvcs"]


def test_percentage_pdb_rounds_up():
    snapshot = extract("hotel-reservation", saved_output(KUBECTL_OUTPUT))
    assert deployment("profile", snapshot)["min_replicas"] == 1  # 50% of 2


def test_no_pdb_means_unknown_minimum():
    snapshot = extract("hotel-reservation", saved_output(KUBECTL_OUTPUT))
    assert deployment("search", snapshot)["min_replicas"] is None


def test_recreate_strategy_takes_every_pod_down():
    snapshot = extract("hotel-reservation", saved_output(KUBECTL_OUTPUT))
    mongo = deployment("mongodb-geo", snapshot)
    assert mongo["max_unavailable"] == "100%"
    assert mongo["max_surge"] == 0


def fake_cluster(deployments: list, pdbs: list):
    """A runner with hand-made lists, for the PDB edge cases."""
    answers = {"deployments": deployments, "pdb": pdbs, "pods": [], "pvc": []}

    def run(command: str) -> str:
        resource = command.split()[2]
        return json.dumps({"items": answers[resource]})

    return run


def web(replicas: int) -> dict:
    return {
        "metadata": {"name": "web", "namespace": "ns"},
        "spec": {"replicas": replicas, "template": {"metadata": {"labels": {"app": "web", "tier": "front"}}}},
    }


def pdb(spec: dict) -> dict:
    return {"metadata": {"name": "p"}, "spec": spec}


@pytest.mark.parametrize(
    ("pdbs", "minimum"),
    [
        (
            [pdb({"minAvailable": "50%", "selector": {"matchLabels": {"app": "web"}}})],
            2,
        ),  # 50% of 3 = 1.5 -> 2
        ([pdb({"minAvailable": 1, "selector": {}})], 1),  # an empty selector picks every pod
        ([pdb({"minAvailable": 1, "selector": {"matchLabels": {"app": "db"}}})], None),  # not this app
        ([pdb({"maxUnavailable": 1, "selector": {"matchLabels": {"app": "web"}}})], None),  # not read in F1
        (
            [
                pdb(
                    {
                        "minAvailable": 1,
                        "selector": {"matchExpressions": [{"key": "app", "operator": "Exists"}]},
                    }
                )
            ],
            None,
        ),
        (
            [
                pdb({"minAvailable": 1, "selector": {"matchLabels": {"app": "web"}}}),
                pdb({"minAvailable": 2, "selector": {"matchLabels": {"tier": "front"}}}),
            ],
            None,  # two PDBs select the same pods: ambiguous
        ),
    ],
)
def test_minimum_from_pdb(pdbs, minimum):
    snapshot = extract("ns", fake_cluster([web(3)], pdbs))
    assert snapshot["deployments"][0]["min_replicas"] == minimum


def test_read_only_check():
    assert is_read_only("kubectl get pods -n ns -o json")
    assert not is_read_only("kubectl delete pod x -n ns")
    assert not is_read_only("rm -rf /")


def test_saved_output_refuses_writes_and_unknown_commands():
    run = saved_output(KUBECTL_OUTPUT)
    with pytest.raises(ValueError):
        run("kubectl delete pod geo-1 -n hotel-reservation")
    with pytest.raises(LookupError):
        run("kubectl get deployments -n nowhere -o json")


def test_live_kubectl_pins_the_context_and_refuses_writes(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout='{"items": []}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run = live_kubectl("kind-argus-dev")
    assert run("kubectl get pods -n ns -o json") == '{"items": []}'
    assert calls[0] == ["kubectl", "get", "pods", "-n", "ns", "-o", "json", "--context", "kind-argus-dev"]
    with pytest.raises(ValueError):
        run("kubectl scale deployment geo --replicas=0 -n ns")
    assert len(calls) == 1
