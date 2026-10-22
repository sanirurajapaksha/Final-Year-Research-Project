import pytest

from argus.diagnosis.core.config import DiagnosisConfig, preset


def test_defaults_are_full_method():
    c = DiagnosisConfig()
    assert (c.k, c.use_h0, c.use_eig, c.backtracking) == (3, True, True, True)
    assert c.graph_priors == "almanac"
    assert c.params.theta == 0.80


def test_greedy_preset_turns_everything_off():
    c = preset("greedy", namespace="social-network")
    assert c.k == 1 and not (c.use_h0 or c.use_eig or c.backtracking)
    assert c.graph_priors == "off"
    assert c.namespace == "social-network"


def test_a5_hop_preset_only_changes_the_graph_prior():
    assert preset("A5-hop") == DiagnosisConfig(graph_priors="hop")


def test_old_boolean_graph_priors_still_work():
    assert DiagnosisConfig(graph_priors=True).graph_priors == "almanac"
    assert DiagnosisConfig(graph_priors=False).graph_priors == "off"


def test_unknown_graph_priors_fails():
    with pytest.raises(ValueError):
        DiagnosisConfig(graph_priors="hops")


def test_override_wins_over_preset():
    assert preset("greedy", k=2).k == 2


def test_unknown_preset_fails():
    with pytest.raises(KeyError):
        preset("nope")
