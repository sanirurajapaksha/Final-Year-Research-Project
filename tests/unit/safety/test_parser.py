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


@pytest.mark.parametrize(
    "command",
    [
        "kubectl scale deploy geo --replicas=1",
        "kubectl delete pod coredns-1",
        "kubectl delete pvc geo-pvc",
    ],
)
def test_missing_namespace_is_rejected(command):
    # kubectl would use its current context's namespace (e.g. kube-system), which M3 can't see.
    with pytest.raises(ParseError, match="missing -n"):
        parse(command)


def test_negative_replicas_parse_so_the_encoding_can_block_them():
    assert parse("kubectl scale deploy geo --replicas=-1 -n hr").params["replicas"] == -1


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("kubectl delete pod geo-1 -n hr", Action("delete", "pod", "geo-1", "hr")),
        ("kubectl delete po/geo-1 --namespace=hr", Action("delete", "pod", "geo-1", "hr")),
        ("kubectl delete pvc geo-pvc -n hr", Action("delete", "pvc", "geo-pvc", "hr")),
        ("kubectl delete persistentvolumeclaim geo-pvc -n hr", Action("delete", "pvc", "geo-pvc", "hr")),
        ("kubectl delete ns kube-system", Action("delete", "namespace", "kube-system", "kube-system")),
        ("kubectl delete namespace hr -n other", Action("delete", "namespace", "hr", "hr")),
        ("kubectl delete pod geo-1 -A", Action("delete", "pod", "geo-1", "*", {"all_namespaces": True})),
        (
            "kubectl delete pod geo-1 --all-namespaces",
            Action("delete", "pod", "geo-1", "*", {"all_namespaces": True}),
        ),
    ],
)
def test_delete_forms(command, expected):
    assert parse(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "kubectl rollout restart deployment/geo -n hr",
        "kubectl rollout restart deploy geo --namespace=hr",
        "kubectl -n hr rollout restart deployments/geo",
    ],
)
def test_rollout_restart_forms(command):
    assert parse(command) == Action("rollout-restart", "deployment", "geo", "hr")


@pytest.mark.parametrize(
    ("command", "reason_part"),
    [
        ("kubectl label pod geo-1 team=sre -n hr", "not supported"),
        ("kubectl rollout undo deploy/geo -n hr", "only 'kubectl rollout restart'"),
        ("kubectl rollout restart -n hr", "exactly one resource"),
        ("kubectl rollout restart deployment -n hr", "exactly one resource"),
        ("kubectl rollout restart statefulset/db -n hr", "only deployments"),
        ("kubectl rollout restart deploy/geo -l app=geo -n hr", "unsupported flag"),
        ("kubectl rollout restart deploy/geo", "missing -n"),
        ("kubectl delete deploy geo -n hr", "only pods, PVCs and namespaces"),
        ("kubectl delete pods -l app=geo -n hr", "unsupported flag"),
        ("kubectl delete pods --all -n hr", "unsupported flag"),
        ("kubectl delete pod geo-1 --force --grace-period=0 -n hr", "unsupported flag"),
        ("kubectl delete pod geo-1 geo-2 -n hr", "exactly one resource"),
        ("kubectl delete pod geo-1 -n", "needs a value"),
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
