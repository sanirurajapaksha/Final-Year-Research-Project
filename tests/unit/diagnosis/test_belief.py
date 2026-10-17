import pytest

from argus.diagnosis.belief import H0, BeliefState


def approx(x):
    return pytest.approx(x, abs=1e-3)


def start() -> BeliefState:
    bs = BeliefState()
    bs.init({"H1": 0.35, "H2": 0.30, "H3": 0.20})
    return bs


# ---------- happy paths ----------


def test_init_gives_h0_its_prior_and_shares_the_rest():
    bs = start()
    assert bs.belief == {"H1": approx(0.35), "H2": approx(0.30), "H3": approx(0.20), H0: approx(0.15)}


def test_worked_example_port_mismatch_reaches_stop():
    bs = start()

    # Evidence 1: `describe svc` shows targetPort 27018 vs containerPort 27017
    bs.update({"H1": "strong-support"}, "E1")
    assert bs.belief["H1"] == approx(0.683)
    assert bs.decide() == "continue"  # 68% is not enough yet

    # Evidence 2: logs say "connection refused" (wrong port, not a NetworkPolicy timeout)
    bs.update({"H1": "strong-support", "H2": "weak-refute", "H3": "strong-refute"}, "E2")
    assert bs.belief["H1"] == approx(0.946)
    assert bs.decide() == "stop"
    assert bs.status["H3"] == "pruned"
    assert bs.ranked()[0][0] == "H1"


def test_all_refuted_triggers_rehypothesize_and_new_hypothesis_inherits_h0():
    bs = start()
    bs.update({"H1": "strong-refute", "H2": "strong-refute", "H3": "strong-refute"}, "E1")
    assert bs.belief[H0] == approx(0.638)
    assert bs.decide() == "rehypothesize"

    bs.add_hypotheses(["H4"])
    assert bs.belief["H4"] == approx(0.511)
    assert bs.belief[H0] == approx(0.128)
    assert sum(bs.belief.values()) == approx(1.0)


def test_history_records_every_change():
    bs = start()
    bs.update({"H1": "weak-support"}, "E1")
    assert [e["event"] for e in bs.history] == ["init", "update"]
    assert bs.history[-1]["evidence"] == "E1"


# ---------- failure paths ----------


def test_init_rejects_empty_scores():
    with pytest.raises(ValueError):
        BeliefState().init({})


def test_init_rejects_zero_score():
    with pytest.raises(ValueError):
        BeliefState().init({"H1": 0.5, "H2": 0.0})


def test_add_hypotheses_rejects_duplicate_id():
    bs = start()
    with pytest.raises(ValueError):
        bs.add_hypotheses(["H1"])


def test_unknown_hypothesis_in_verdicts_is_ignored():
    bs = start()
    bs.update({"H9": "strong-support"}, "E1")  # an LLM inventing an id must not change anything
    assert bs.belief["H1"] == approx(0.35)
