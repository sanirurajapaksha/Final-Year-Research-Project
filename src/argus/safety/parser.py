"""Deterministic parser: command string -> structured action (no LLM).

Template path for common verbs. The F1 slice supports one form:

    kubectl scale (deployment NAME | deployment/NAME) --replicas=N [-n NAMESPACE]

Anything else raises ParseError, which the gate turns into BLOCK. Unknown flags are rejected
rather than ignored, because ignoring a flag could change what the command does.
Run the pre-filter first: this module assumes a single, plain kubectl command.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from argus.safety.prefilter import find_subcommand, tokenize

DEPLOYMENT_ALIASES = {"deployment", "deployments", "deploy"}
DEFAULT_NAMESPACE = "default"
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
    if subcommand != "scale":
        raise ParseError(f"'kubectl {subcommand}' is not supported in the F1 slice (only 'kubectl scale')")
    return _parse_scale(tokens)


def _parse_scale(tokens: list[str]) -> Action:
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

    unknown = set(flags) - {"replicas", "namespace"}
    if unknown:
        raise ParseError(f"unsupported flag(s) for the F1 slice: {', '.join(sorted(unknown))}")

    kind, name = _resource(positional)

    if "replicas" not in flags:
        raise ParseError("missing --replicas")
    replicas_text = flags["replicas"]
    if not INTEGER.fullmatch(replicas_text):
        raise ParseError(f"--replicas must be an integer, got {replicas_text!r}")

    namespace = flags.get("namespace", DEFAULT_NAMESPACE)
    if not namespace:
        raise ParseError("empty namespace")

    return Action(
        verb="scale",
        kind=kind,
        name=name,
        namespace=namespace,
        params={"replicas": int(replicas_text)},
    )


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
    return raw_flag.lstrip("-")


def _resource(positional: list[str]) -> tuple[str, str]:
    if len(positional) == 1 and "/" in positional[0]:
        kind, name = positional[0].split("/", 1)
    elif len(positional) == 2:
        kind, name = positional
    else:
        raise ParseError("expected exactly one resource: 'deployment NAME' or 'deployment/NAME'")

    if kind.lower() not in DEPLOYMENT_ALIASES:
        raise ParseError(f"only deployments are supported in the F1 slice, got {kind!r}")
    if not name:
        raise ParseError("empty resource name")
    return "deployment", name
