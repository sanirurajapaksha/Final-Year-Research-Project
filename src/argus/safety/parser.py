"""Deterministic parser: command string -> structured action (no LLM).

Template path for common verbs. The F1 slice supports two forms:

    kubectl scale (deployment NAME | deployment/NAME) --replicas=N -n NAMESPACE
    kubectl delete (pod | pvc) NAME (-n NAMESPACE | -A)
    kubectl delete namespace NAME

Anything else raises ParseError, which the gate turns into BLOCK. Unknown flags are rejected
rather than ignored, because ignoring a flag could change what the command does.
The namespace must be given: without -n, kubectl uses its current context's namespace, which
M3 can't see, so M3 could check a different object from the one that is changed.
Run the pre-filter first: this module assumes a single, plain kubectl command.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from argus.safety.prefilter import find_subcommand, tokenize

DEPLOYMENT_ALIASES = {"deployment", "deployments", "deploy"}
# Kinds `kubectl delete` may target in F1, as typed -> the name M3 uses.
DELETE_KINDS = {
    "pod": "pod",
    "pods": "pod",
    "po": "pod",
    "pvc": "pvc",
    "pvcs": "pvc",
    "persistentvolumeclaim": "pvc",
    "persistentvolumeclaims": "pvc",
    "namespace": "namespace",
    "namespaces": "namespace",
    "ns": "namespace",
}
ALL_NAMESPACES = "*"  # the namespace recorded for -A
INTEGER = re.compile(r"-?\d+")


class ParseError(ValueError):
    """The command isn't in a form this parser supports, or is malformed."""


@dataclass(frozen=True)
class Action:
    verb: str
    kind: str
    name: str
    namespace: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_request(self) -> dict[str, Any]:
        return {
            "verb": self.verb,
            "kind": self.kind,
            "name": self.name,
            "namespace": self.namespace,
            "params": dict(self.params),
        }


def parse(command: str) -> Action:
    tokens = tokenize(command)
    subcommand = find_subcommand(tokens)
    if subcommand == "scale":
        return _parse_scale(tokens)
    if subcommand == "delete":
        return _parse_delete(tokens)
    raise ParseError(f"'kubectl {subcommand}' is not supported in the F1 slice (only 'scale' and 'delete')")


def _parse_scale(tokens: list[str]) -> Action:
    positional, flags = _split_args(tokens)
    _reject_unknown_flags(flags, {"replicas", "namespace"})

    kind, name = _resource(positional)
    if kind not in DEPLOYMENT_ALIASES:
        raise ParseError(f"only deployments are supported in the F1 slice, got {kind!r}")

    if "replicas" not in flags:
        raise ParseError("missing --replicas")
    replicas_text = flags["replicas"]
    if not INTEGER.fullmatch(replicas_text):
        raise ParseError(f"--replicas must be an integer, got {replicas_text!r}")

    return Action(
        verb="scale",
        kind="deployment",
        name=name,
        namespace=_namespace(flags),
        params={"replicas": int(replicas_text)},
    )


def _parse_delete(tokens: list[str]) -> Action:
    positional, flags = _split_args(tokens)
    # Selectors (-l) and --all are rejected here as unknown flags: they can't be checked one object at a time.
    _reject_unknown_flags(flags, {"namespace", "all_namespaces"})

    typed_kind, name = _resource(positional)
    if typed_kind not in DELETE_KINDS:
        raise ParseError(f"only pods, PVCs and namespaces can be deleted in the F1 slice, got {typed_kind!r}")
    kind = DELETE_KINDS[typed_kind]

    if kind == "namespace":
        # A namespace isn't inside another namespace. The namespace that changes is the one deleted.
        namespace = name
    elif "all_namespaces" in flags:
        namespace = ALL_NAMESPACES
    else:
        namespace = _namespace(flags)

    params = {}
    if "all_namespaces" in flags:
        params["all_namespaces"] = True

    return Action(verb="delete", kind=kind, name=name, namespace=namespace, params=params)


def _split_args(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split the tokens after 'kubectl' into positional words (after the subcommand) and flags."""
    positional: list[str] = []
    flags: dict[str, str] = {}
    seen_subcommand = False

    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            name, value, i = _read_flag(tokens, i)
            if name in flags:
                raise ParseError(f"flag {name} given twice")
            flags[name] = value
            continue
        if not seen_subcommand:
            seen_subcommand = True
        else:
            positional.append(token)
        i += 1
    return positional, flags


def _reject_unknown_flags(flags: dict[str, str], allowed: set[str]) -> None:
    unknown = set(flags) - allowed
    if unknown:
        raise ParseError(f"unsupported flag(s) for the F1 slice: {', '.join(sorted(unknown))}")


def _namespace(flags: dict[str, str]) -> str:
    if "namespace" not in flags:
        raise ParseError("missing -n: kubectl would use its current context's namespace, which M3 can't see")
    namespace = flags["namespace"]
    if not namespace:
        raise ParseError("empty namespace")
    return namespace


def _read_flag(tokens: list[str], i: int) -> tuple[str, str, int]:
    """Read one flag starting at tokens[i]; return (canonical name, value, next index)."""
    token = tokens[i]
    if "=" in token:
        raw, value = token.split("=", 1)
        return _canonical(raw), value, i + 1
    raw = token
    name = _canonical(raw)
    if name in ("replicas", "namespace"):
        if i + 1 >= len(tokens):
            raise ParseError(f"flag {raw} needs a value")
        return name, tokens[i + 1], i + 2
    return name, "", i + 1


def _canonical(raw_flag: str) -> str:
    if raw_flag in ("-n", "--namespace"):
        return "namespace"
    if raw_flag == "--replicas":
        return "replicas"
    if raw_flag in ("-A", "--all-namespaces"):
        return "all_namespaces"
    return raw_flag.lstrip("-")


def _resource(positional: list[str]) -> tuple[str, str]:
    """Return (kind as typed, in lower case, name) from 'KIND NAME' or 'KIND/NAME'."""
    if len(positional) == 1 and "/" in positional[0]:
        kind, name = positional[0].split("/", 1)
    elif len(positional) == 2:
        kind, name = positional
    else:
        raise ParseError("expected exactly one resource: 'KIND NAME' or 'KIND/NAME'")

    if not name:
        raise ParseError("empty resource name")
    return kind.lower(), name
