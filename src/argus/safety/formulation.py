"""Step 2a: Formulation Agent (LLM). v0 reads `kubectl patch deployment` only. Prompt-tuned (D8).

The fixed parser reads scale, delete and rollout restart. For a patch, an LLM describes what the
command changes as a small typed object (the IR). M3 then:
    1. validates the IR against the schema (Pydantic);
    2. cross-checks it against the command text: the name, the -n namespace, and which part of
       the deployment the patch touches. Any disagreement blocks;
    3. maps it to an action the existing rules already check:
           set_replicas         -> scale            (I1, I2)
           pod_template_change  -> rollout-restart  (I3, I2): a template change starts a rolling update
           metadata_only        -> patch-metadata   (I2 only): labels and annotations only
           unknown              -> BLOCK

LLM output is data: it is validated, never executed. Every raw output is appended to a JSONL log.
Privacy: the whole command, including any values in the patch (env values, for example), is sent
to OpenRouter and written to that log. Don't put secrets in patches; redaction isn't built.
"""

import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from argus.llm.client import LLMError, complete_json
from argus.safety import parser
from argus.safety.prefilter import find_subcommand, tokenize

LLM_TIMEOUT_S = 20.0


class FormulationError(ValueError):
    """The command can't be formulated safely, so the gate blocks it."""


class PatchIR(BaseModel):
    """What the LLM says a patch does."""

    kind: Literal["deployment", "other"]
    name: str
    namespace: str
    effect: Literal["set_replicas", "pod_template_change", "metadata_only", "unknown"]
    replicas: int


# The same fields as PatchIR, as the JSON Schema the model must answer in.
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["deployment", "other"]},
        "name": {"type": "string"},
        "namespace": {"type": "string"},
        "effect": {
            "type": "string",
            "enum": ["set_replicas", "pod_template_change", "metadata_only", "unknown"],
        },
        "replicas": {"type": "integer"},
    },
    "required": ["kind", "name", "namespace", "effect", "replicas"],
    "additionalProperties": False,
}

PROMPT = """You read one kubectl patch command and describe what it changes.
Answer only with JSON that matches the schema.

- kind: "deployment" if the command patches a Deployment, otherwise "other".
- name: the resource name, exactly as written in the command.
- namespace: the value of -n or --namespace, exactly as written, or "" if there is none.
- effect:
  "set_replicas" if the patch sets only spec.replicas;
  "pod_template_change" if the patch changes only spec.template (containers, images, env,
    resources, or the pods' labels and annotations);
  "metadata_only" if the patch changes only the Deployment's own metadata (its labels or annotations);
  "unknown" for anything else, including a patch that changes more than one of these, or if unsure.
- replicas: the new spec.replicas if effect is "set_replicas", otherwise 0.

Command:
"""


def handles(command: str) -> bool:
    """True for the commands v0 formulates: `kubectl patch`."""
    try:
        return find_subcommand(tokenize(command)) == "patch"
    except ValueError:
        return False


def formulate(command: str, model: str, log_path: str) -> parser.Action:
    """Turn a `kubectl patch deployment` command into an action M3's rules check."""
    # Read what the command text says without the LLM, to check the LLM's answer against it.
    positional, flags = parser.split_args(tokenize(command))
    for flag in flags:
        if flag not in ("namespace", "patch", "type"):
            raise FormulationError(f"unsupported flag for patch: {flag}")
    kind, name = parser.resource(positional)
    if kind not in parser.DEPLOYMENT_ALIASES:
        raise FormulationError(f"v0 formulates patches to deployments only, got {kind!r}")
    namespace = parser.required_namespace(flags)
    if flags.get("type", "strategic") not in ("strategic", "merge"):
        raise FormulationError("v0 reads strategic and merge patches only")
    if "patch" not in flags:
        raise FormulationError("missing -p/--patch")
    effect_in_text, replicas_in_text = _effect_of(flags["patch"])

    try:
        raw, usage = complete_json(PROMPT + command, SCHEMA, model, LLM_TIMEOUT_S)
    except LLMError as exc:
        raise FormulationError(f"LLM: {exc}") from exc
    # Every raw answer is evidence: if it can't be kept, the command is blocked.
    try:
        _log(log_path, command, model, raw, usage)
    except OSError as exc:
        raise FormulationError(f"can't keep the raw LLM answer: {type(exc).__name__}: {exc}") from exc

    try:
        ir = PatchIR.model_validate_json(raw)
    except ValidationError as exc:
        raise FormulationError(f"LLM answer doesn't match the schema: {exc.errors()[0]['msg']}") from exc

    # Cross-checks: the LLM must agree with the command text.
    if ir.kind != "deployment" or ir.name != name or ir.namespace != namespace:
        raise FormulationError(f"LLM read a different target: {ir.kind} {ir.namespace}/{ir.name}")
    if ir.effect != effect_in_text:
        raise FormulationError(f"LLM says {ir.effect!r}, but the patch text is {effect_in_text!r}")
    if ir.effect == "set_replicas" and ir.replicas != replicas_in_text:
        raise FormulationError(f"LLM says replicas={ir.replicas}, the patch says {replicas_in_text}")

    if ir.effect == "set_replicas":
        return parser.Action("scale", "deployment", name, namespace, {"replicas": ir.replicas})
    if ir.effect == "pod_template_change":
        return parser.Action("rollout-restart", "deployment", name, namespace)
    if ir.effect == "metadata_only":
        return parser.Action("patch-metadata", "deployment", name, namespace)
    raise FormulationError("the LLM can't say what this patch does (unknown effect)")


def _effect_of(patch_text: str) -> tuple[str, int | None]:
    """Which one part of a deployment a patch touches, read from the JSON itself."""
    try:
        patch = json.loads(patch_text, object_pairs_hook=_reject_duplicate_keys)
    except ValueError:  # not JSON, or a key given twice
        return "unknown", None
    if not isinstance(patch, dict):
        return "unknown", None
    if set(patch) == {"metadata"}:
        if _labels_or_annotations_only(patch["metadata"]):
            return "metadata_only", None
        return "unknown", None
    spec = patch.get("spec")
    if set(patch) == {"spec"} and isinstance(spec, dict):
        if set(spec) == {"replicas"} and type(spec["replicas"]) is int:
            return "set_replicas", spec["replicas"]
        if set(spec) == {"template"}:
            return "pod_template_change", None
    return "unknown", None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object, refusing a key given twice.

    Python keeps the last value of a repeated key; kubectl or the API server might not, so M3
    could check a different value from the one that runs.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _labels_or_annotations_only(metadata: Any) -> bool:
    """True if a metadata patch sets only labels and/or annotations, each a map of strings.

    Other metadata changes what Kubernetes does with the object (ownerReferences can make it
    garbage-collected, finalizers can block its deletion), which M3 doesn't model.
    """
    if not isinstance(metadata, dict) or not metadata:
        return False
    for key, value in metadata.items():
        if key not in ("labels", "annotations") or not isinstance(value, dict):
            return False
        for text in value.values():
            if not isinstance(text, str):
                return False
    return True


def _log(log_path: str, command: str, model: str, raw: str, usage: dict) -> None:
    """Append one raw LLM answer to the JSONL log (W3-02: keep every raw output)."""
    if not log_path:
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": model}
    entry["command"] = command
    entry["raw"] = raw
    entry["usage"] = usage
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry) + "\n")
