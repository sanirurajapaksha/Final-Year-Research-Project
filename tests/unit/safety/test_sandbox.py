import os

import pytest

from argus.safety import sandbox

REQUEST = {
    "action": {
        "verb": "scale",
        "kind": "deployment",
        "name": "geo",
        "namespace": "hr",
        "params": {"replicas": 1},
    },
    "facts": {"replicas": 3, "min_replicas": 2},
    "timeout_ms": 2000,
}


def test_round_trip_returns_the_raw_result():
    outcome = sandbox.run(REQUEST, timeout_s=30, memory_mb=512)
    assert outcome.error is None
    assert outcome.result["z3_result"] == "sat"


def test_timeout_returns_no_result():
    outcome = sandbox.run(REQUEST, timeout_s=0.001, memory_mb=512)
    assert outcome.result is None
    assert "timeout" in outcome.error


def test_worker_error_returns_no_result():
    outcome = sandbox.run({"action": {"verb": "nonsense"}}, timeout_s=30, memory_mb=512)
    assert outcome.result is None
    assert "exited with code 2" in outcome.error


@pytest.mark.skipif(os.name != "posix", reason="the memory cap uses the Unix-only resource module")
def test_memory_cap_is_enforced():
    outcome = sandbox.run(REQUEST, timeout_s=30, memory_mb=8)
    assert outcome.result is None
