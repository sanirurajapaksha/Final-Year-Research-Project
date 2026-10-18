import typing

import pytest
from pydantic import ValidationError

from argus.diagnosis.belief import LAMBDA
from argus.diagnosis.models import HypothesisSpec, Verdict


def test_verdict_words_match_belief_weights():
    assert set(typing.get_args(Verdict)) == set(LAMBDA)


def test_hypothesis_label():
    h = HypothesisSpec(component="user-service", layer="k8s-network", fault="targetPort mismatch",
                       test="kubectl get svc user-service -o yaml")
    assert h.label() == "user-service [k8s-network] targetPort mismatch"
    assert h.id == ""  # ids come from M2, not the LLM


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        HypothesisSpec(component="a", layer="b", fault="c", test="kubectl get pods", confidence=1.5)