import pytest

from argus.diagnosis.core.config import DiagnosisConfig, preset


def test_defaults_are_full_method():
    c = DiagnosisConfig()
    assert (c.k, c.use_h0, c.use_eig, c.backtracking, c.graph_priors) == (3, True, True, True, True)
    assert c.params.theta == 0.80


def test_greedy_preset_turns_everything_off():
    c = preset("greedy", namespace="social-network")
    assert c.k == 1 and not (c.use_h0 or c.use_eig or c.backtracking or c.graph_priors)
    assert c.namespace == "social-network"


def test_override_wins_over_preset():
    assert preset("greedy", k=2).k == 2


def test_unknown_preset_fails():
    with pytest.raises(KeyError):
        preset("nope")
