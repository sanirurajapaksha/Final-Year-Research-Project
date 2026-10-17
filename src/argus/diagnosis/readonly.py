"""Read-only guard for the kubectl commands M2 asks to run.

M2 never changes the cluster. Every read it proposes must pass `is_read_only`, which allows a
small set of inspection verbs and rejects shell metacharacters, watch/follow/edit flags, and any
flag that would point the command at another cluster or identity.
"""

import shlex

ALLOWED = {
    "get",
    "describe",
    "logs",
    "top",
    "events",
    "explain",
    "api-resources",
    "api-versions",
    "version",
    "cluster-info",
}
ALLOWED_PAIRS = {("auth", "can-i")}
DENY_FLAGS = {"-f", "--follow", "-w", "--watch", "--watch-only", "--edit", "--overwrite", "-i", "-it", "-t"}
# The cluster and identity are fixed by the caller (the kube context), never by the LLM.
TARGET_FLAGS = {"--context", "--kubeconfig", "--cluster", "--user", "--server", "-s", "--token", "--as"}
NAMESPACE_FLAGS = {"-n", "--namespace"}
META = ("|", ";", "&", ">", "<", "`", "$(", "\n")


def is_read_only(cmd: str) -> bool:
    if any(m in cmd for m in META):
        return False
    try:
        toks = shlex.split(cmd)
    except ValueError:
        return False
    if len(toks) < 2 or toks[0] != "kubectl":
        return False
    args = toks[1:]
    if any(t.split("=", 1)[0] in TARGET_FLAGS | DENY_FLAGS for t in args):
        return False
    i = 0
    while i < len(args) and args[i].startswith("-"):  # namespace flag before the verb
        i += 2 if args[i] in NAMESPACE_FLAGS else 1
    if i >= len(args):
        return False
    verb, rest = args[i], args[i + 1 :]
    if verb == "auth":
        return bool(rest) and (verb, rest[0]) in ALLOWED_PAIRS
    return verb in ALLOWED
