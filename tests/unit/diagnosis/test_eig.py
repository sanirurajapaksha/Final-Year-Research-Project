import pytest

from argus.diagnosis.eig import PRED, eig, entropy, rank_tests

BELIEF = {"H1": 0.35, "H2": 0.30, "H3": 0.20, "H0": 0.15}

# P(test comes back positive | hypothesis) for the worked example
MATRIX = {
    "describe_svc": {"H1": 0.9, "H2": 0.1, "H3": 0.1, "H0": 0.1},
    "get_netpol": {"H1": 0.1, "H2": 0.1, "H3": 0.9, "H0": 0.1},
    "logs": {"H1": 0.9, "H2": 0.3, "H3": 0.1, "H0": 0.3},
    "get_pods": {"H1": 0.2, "H2": 0.9, "H3": 0.2, "H0": 0.3},
}


def approx(x):
    return pytest.approx(x, abs=1e-3)


# ---------- happy paths ----------


def test_entropy_bounds():
    assert entropy([0.25] * 4) == approx(2.0)  # maximum doubt over 4 options
    assert entropy([1.0]) == approx(0.0)  # certain
    assert entropy(BELIEF.values()) == approx(1.926)


def test_worked_example_picks_describe_svc_first():
    ranked = rank_tests(BELIEF, MATRIX)
    assert [t for t, _ in ranked] == ["describe_svc", "get_netpol", "logs", "get_pods"]
    assert ranked[0][1] == approx(0.489)


def test_test_that_everyone_predicts_the_same_has_zero_gain():
    useless = {h: 0.9 for h in BELIEF}
    assert eig(BELIEF, useless) == approx(0.0)


def test_cost_can_change_the_winner():
    ranked = rank_tests(BELIEF, MATRIX, cost={"describe_svc": 2.0})
    assert ranked[0][0] == "get_netpol"


def test_pred_words_cover_the_scale():
    assert PRED["very_likely"] > PRED["likely"] > PRED["unsure"] > PRED["unlikely"] > PRED["very_unlikely"]


# ---------- failure / edge paths ----------


def test_no_tests_gives_empty_ranking():
    assert rank_tests(BELIEF, {}) == []


def test_already_certain_gains_nothing():
    assert eig({"H1": 1.0}, {"H1": 0.9}) == approx(0.0)


def test_impossible_outcome_does_not_divide_by_zero():
    # P(positive) is 0 for everyone: must return a number, not crash
    assert eig(BELIEF, {h: 0.0 for h in BELIEF}) == approx(0.0)


def test_missing_prediction_is_an_error():
    with pytest.raises(KeyError):
        eig(BELIEF, {"H1": 0.9})  # the Flow must fill every hypothesis before calling this