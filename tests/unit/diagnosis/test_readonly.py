import pytest

from argus.diagnosis.readonly import is_read_only

ALLOWED = [
    "kubectl get pods -n hotel -o wide",
    "kubectl -n hotel get svc mongodb-user -o yaml",
    "kubectl describe svc mongodb-user -n hotel",
    "kubectl logs deploy/user-service -n hotel --tail=50",
    "kubectl logs user-service-7d9 --previous -n hotel",
    "kubectl get events -n hotel --sort-by=.lastTimestamp",
    "kubectl top pods -n hotel",
    "kubectl get pods -n hotel -l app=user-service",
    "kubectl get pods -o jsonpath={.items[*].status.phase}",
    "kubectl auth can-i list pods",
]

BLOCKED = {
    # changes the cluster
    "delete": "kubectl delete pod x -n hotel",
    "patch": "kubectl patch svc a -p {}",
    "apply": "kubectl apply -f a.yaml",
    "scale": "kubectl scale deploy a --replicas=0",
    "edit": "kubectl edit svc a",
    "exec": "kubectl exec -it x -- sh",
    "auth reconcile": "kubectl auth reconcile -f x",
    "config": "kubectl config use-context dr",
    # never finishes
    "follow": "kubectl logs -f x",
    "watch": "kubectl get pods -w",
    # shell tricks
    "pipe": "kubectl get pods | grep x",
    "chain": "kubectl get pods; kubectl delete pod x",
    "subshell": "kubectl get pods $(whoami)",
    "redirect": "kubectl get pods > out.txt",
    "newline": "kubectl get pods\nkubectl delete pod x",
    # wrong cluster or identity
    "context": "kubectl --context dr get pods",
    "context=": "kubectl get pods --context=dr",
    "kubeconfig": "kubectl get pods --kubeconfig /tmp/k",
    "impersonate": "kubectl get pods --as admin",
    # not kubectl / malformed
    "rm": "rm -rf /",
    "helm": "helm list",
    "bare": "kubectl",
    "flags only": "kubectl -n hotel",
    "bad quotes": 'kubectl get pods "unclosed',
}


# ---------- happy path ----------


@pytest.mark.parametrize("cmd", ALLOWED)
def test_read_commands_are_allowed(cmd):
    assert is_read_only(cmd)


# ---------- failure paths ----------


@pytest.mark.parametrize("cmd", BLOCKED.values(), ids=BLOCKED.keys())
def test_unsafe_commands_are_blocked(cmd):
    assert not is_read_only(cmd)


def test_injection_from_logs_is_blocked():
    # what a prompt-injected LLM might produce after reading malicious log text
    assert not is_read_only("kubectl get pods -n hotel && kubectl delete ns hotel")