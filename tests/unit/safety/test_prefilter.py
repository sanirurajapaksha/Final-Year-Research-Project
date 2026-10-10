import pytest

from argus.safety.prefilter import check


@pytest.mark.parametrize(
    "command",
    [
        "kubectl scale deploy geo --replicas=2 -n hr",
        "kubectl -n hr scale deploy geo --replicas=2",
        'kubectl patch deploy geo -n hr -p \'{"spec":{"replicas":2}}\'',
        "kubectl annotate deploy geo -n hr note='a;b|c'",
    ],
)
def test_plain_kubectl_commands_pass(command):
    assert check(command) is None


@pytest.mark.parametrize(
    ("command", "reason_part"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("rm -rf /", "not a kubectl command"),
        ("kubectl get pods | grep geo", "shell operator '|'"),
        ("kubectl get pods|grep geo", "shell operator '|'"),
        ("kubectl delete pod a; kubectl delete pod b", "shell operator ';'"),
        ("kubectl delete pod a && kubectl delete pod b", "shell operator '&&'"),
        ("kubectl delete pod a || true", "shell operator '||'"),
        ("kubectl delete pod a &", "shell operator '&'"),
        ("kubectl get pods > out.txt", "shell operator '>'"),
        ("kubectl delete pod $(kubectl get pods -o name)", "command substitution"),
        ("kubectl delete pod `whoami`", "command substitution"),
        ("kubectl scale deploy geo --replicas=2\nkubectl delete ns hr", "multi-line"),
        ("kubectl scale deploy geo --replicas=2 -n 'hr", "unbalanced quotes"),
        ("kubectl exec geo -n hr -- rm -rf /data", "kubectl exec"),
        ("kubectl edit deploy geo -n hr", "kubectl edit"),
        ("kubectl port-forward svc/geo 8080:80", "kubectl port-forward"),
        ("kubectl run debug --image=busybox -it", "interactive flag '-it'"),
        ("kubectl run debug --image=busybox --stdin", "interactive flag '--stdin'"),
        ("kubectl apply -f -", "stdin"),
        ("kubectl apply --filename=-", "stdin"),
        ("kubectl", "no kubectl subcommand"),
    ],
)
def test_rejected_shapes(command, reason_part):
    reason = check(command)
    assert reason is not None
    assert reason_part in reason
