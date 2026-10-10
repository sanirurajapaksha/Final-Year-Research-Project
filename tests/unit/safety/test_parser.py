import pytest

from argus.safety.parser import Action, ParseError, parse

GEO_TO_3 = Action(verb="scale", kind="deployment", name="geo", namespace="hr", params={"replicas": 3})


@pytest.mark.parametrize(
    "command",
    [
        "kubectl scale deployment geo --replicas=3 -n hr",
        "kubectl scale deploy/geo --replicas 3 --namespace=hr",
        "kubectl scale deployments geo --replicas=3 --namespace hr",
        "kubectl -n hr scale deploy geo --replicas=3",
        "kubectl scale deploy geo -n=hr --replicas=3",
    ],
)
def test_scale_forms_parse_to_the_same_action(command):
    assert parse(command) == GEO_TO_3


def test_missing_namespace_defaults_to_default():
    assert parse("kubectl scale deploy geo --replicas=1").namespace == "default"


def test_negative_replicas_parse_so_the_encoding_can_block_them():
    assert parse("kubectl scale deploy geo --replicas=-1 -n hr").params["replicas"] == -1


@pytest.mark.parametrize(
    ("command", "reason_part"),
    [
        ("kubectl delete pod geo -n hr", "not supported"),
        ("kubectl scale deploy geo -n hr", "missing --replicas"),
        ("kubectl scale deploy geo --replicas=abc -n hr", "must be an integer"),
        ("kubectl scale deploy geo --replicas=2.5 -n hr", "must be an integer"),
        ("kubectl scale statefulset db --replicas=1 -n hr", "only deployments"),
        ("kubectl scale deploy --all --replicas=0 -n hr", "unsupported flag"),
        ("kubectl scale deploy -l app=geo --replicas=0 -n hr", "unsupported flag"),
        ("kubectl scale deploy geo --replicas=1 --replicas=2 -n hr", "given twice"),
        ("kubectl scale deploy geo frontend --replicas=1 -n hr", "exactly one resource"),
        ("kubectl scale deploy geo --replicas", "needs a value"),
    ],
)
def test_unsupported_or_malformed_commands_raise(command, reason_part):
    with pytest.raises(ParseError, match=reason_part):
        parse(command)
