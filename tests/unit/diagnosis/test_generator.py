from argus.diagnosis.core.models import Candidate, DiagContext, HypothesisSpec
from argus.diagnosis.loop.generator import RuleGenerator, validate

CTX = DiagContext(
    namespace="demo", candidates=[Candidate(service="frontend", weight=1.5), Candidate(service="cart")]
)


def test_rule_generator_gives_k_ids_in_order():
    hyps = RuleGenerator().draft(CTX, k=3)
    assert [h.id for h in hyps] == ["H1", "H2", "H3"]
    assert all(h.component == "frontend" for h in hyps)


def test_refuted_pair_is_skipped_and_ids_continue():
    first = RuleGenerator().draft(CTX, k=1)[0]
    hyps = RuleGenerator().draft(CTX, k=1, refuted={(first.component, first.fault)}, next_id=2)
    assert hyps[0].id == "H2" and hyps[0].fault != first.fault


def test_validate_drops_unknown_component_and_mutating_test():
    bad = [
        HypothesisSpec(component="ghost", layer="x", fault="y", test="kubectl get pods"),
        HypothesisSpec(component="cart", layer="x", fault="y", test="kubectl delete pod cart"),
    ]
    assert validate(bad, CTX, set(), k=3) == []


def test_empty_context_gives_no_hypotheses():
    assert RuleGenerator().draft(DiagContext(namespace="demo"), k=3) == []


def test_per_component_spreads_a_round_over_rival_components():
    hyps = RuleGenerator(per_component=2).draft(CTX, k=3)
    assert [h.component for h in hyps] == ["frontend", "frontend", "cart"]
    assert [h.id for h in hyps] == ["H1", "H2", "H3"]


def test_per_component_fills_from_held_back_specs_when_one_candidate_is_all_there_is():
    one = DiagContext(namespace="demo", candidates=[Candidate(service="cart")])
    hyps = RuleGenerator(per_component=1).draft(one, k=3)
    assert [h.component for h in hyps] == ["cart", "cart", "cart"]


def test_no_per_component_limit_keeps_every_guess_on_the_top_candidate():
    assert {h.component for h in RuleGenerator().draft(CTX, k=3)} == {"frontend"}
