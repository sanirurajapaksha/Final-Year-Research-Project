"""FIX step with the LLM: choose a fix template and fill in its values from the evidence.

By the time this runs, the diagnosis is decided (the belief maths stopped on one hypothesis). The LLM
only picks HOW to repair it, and has the least freedom of any step:
  - it chooses one template from a fixed list (or none); code builds the exact command, so M3 always
    checks a string of a known shape (M3 accepts `kubectl patch deployment` and `rollout restart`);
  - every value it fills in must be visible in the evidence (the env var name in the logs, the
    service name and port in the service list), and must cite the evidence ids that show it.
    This replaces the hard-coded demo address table on the LLM path;
  - a value that fails the checks, or a command M3 already blocked, goes back to it with the reason
    (at most max_revisions more tries: the REVISE step);
  - a fault in the service's own code gets no command: a person has to change the code;
  - a full data volume gets no command either: a restart crashes again on the same full disk, and
    deleting the PVC loses the data. M2 reads the deployment and its PVC and hands a person the
    expansion command instead (M3 has no rule for `kubectl patch pvc`, so it can't check one).
For an app-config fault M2 first runs one more read-only command, `kubectl get services`, so the right
address can come from the cluster. With no LLM, or after the tries run out, the rule fixes in fixes.py
are used, checked against M3's blocks exactly as before.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from argus.contracts import ProposedAction, SafetyVerdict
from argus.diagnosis.core.models import DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.loop.context_adapter import NAMED_SERVICE, NOT_A_SERVICE
from argus.diagnosis.loop.fixes import patch_env_command, propose_fix, restart_command
from argus.diagnosis.loop.generator import SERVICE_NAME
from argus.diagnosis.ports.base import LLMClient, LLMUnavailable, ReadExecutor, guarded_run
from argus.diagnosis.ports.fakes import NoLLM, NullReadExecutor

ENV_VAR = re.compile(r"[A-Z][A-Z0-9_]*")
SAFE_VALUE = re.compile(r"[A-Za-z0-9._:/-]{1,200}")  # no quotes, spaces or shell characters

# template id -> (fault layers it may fix, what it does, which values it uses)
TEMPLATES: dict[str, tuple[tuple[str, ...], str, str]] = {
    "set-env": (
        ("app-config",),
        "Set one env var on the target deployment's container of the same name (a kubectl patch of "
        "the pod template; the pods are replaced with the new setting).",
        "target, var, value",
    ),
    "restart": (
        ("k8s-network", "resources", "dependency"),
        "Rolling restart of the target deployment (kubectl rollout restart).",
        "target",
    ),
}
HUMAN_LAYERS = {"code"}
HUMAN_NOTE = (
    "human_pr_required: the diagnosed fault is in the service's own code, which no kubectl command "
    "can fix safely, so M2 proposes no write."
)
SIZE = re.compile(r"(\d+)(Ki|Mi|Gi|Ti)")


class FixAnswer(BaseModel):
    template: Literal["set-env", "restart", "none"]
    target: str
    var: str
    value: str
    cited: list[str]
    rationale: str


@dataclass
class FixOutcome:
    action: ProposedAction | None
    source: Literal["llm", "rules", "none"]
    note: str = ""  # why there is no write, when there is none
    lookups: list[Evidence] = field(default_factory=list)  # extra reads run for this step


def blocked_note(verdict: SafetyVerdict) -> str:
    """Why the fix was dropped: M3's reason and counterexample, and that no other write follows."""
    line = f"M3 blocked the fix `{verdict.command}`: {verdict.reason}"
    if verdict.counterexample:
        line += f"; counterexample: {json.dumps(verdict.counterexample, sort_keys=True)}"
    return line + ". M2 knows no other safe fix for this fault, so it proposes no write."


class FixProposer:
    def __init__(
        self, llm: LLMClient | None = None, reads: ReadExecutor | None = None, max_revisions: int = 2
    ) -> None:
        self.llm = llm or NoLLM()
        self.reads = reads or NullReadExecutor()
        self.max_revisions = max_revisions

    def propose(
        self,
        top: HypothesisSpec,
        ctx: DiagContext,
        evidence: list[Evidence],
        blocked: dict[str, SafetyVerdict],
    ) -> FixOutcome:
        if top.layer in HUMAN_LAYERS:
            return FixOutcome(None, "none", HUMAN_NOTE)
        if top.layer == "storage":
            return self._storage_handoff(top, ctx)
        allowed = [t for t, (layers, _, _) in TEMPLATES.items() if top.layer in layers]
        if allowed and not isinstance(self.llm, NoLLM):
            outcome = self._ask(top, ctx, evidence, blocked, allowed)
            if outcome is not None:
                return outcome
        return self._rules(top, ctx, blocked)

    # ---------- the LLM path ----------

    def _ask(self, top, ctx, evidence, blocked, allowed) -> FixOutcome | None:
        lookups = self._lookups(top, ctx)
        seen = [e for e in [*evidence, *lookups] if e.ok]
        # Names may come from the logs (the env var an error names); values only from what a read showed:
        # logs use short names ("redis"), while an address must be the real Service ("redis-cart").
        outputs = "\n".join(e.output for e in seen)
        grounding = {"names": "\n".join([*ctx.symptoms, outputs]), "values": outputs}
        # M1's signal lines go in too (as S1): the error that names what the component cannot reach is
        # usually the only place that says which Service an address must point at.
        signals = {"id": "S1", "command": "M1 anomaly signals", "output": "\n".join(ctx.symptoms)}
        shown = [*({"id": e.id, "command": e.command, "output": e.output} for e in seen), signals]
        rejected = [f"{cmd}: blocked by M3 ({v.reason})" for cmd, v in blocked.items()]
        for _ in range(1 + self.max_revisions):
            try:
                answer = self.llm.structured(
                    "fix",
                    FixAnswer,
                    diagnosis=f"{top.label()} (confirmed by the reads; expected: {top.expected})",
                    evidence=shown,
                    templates=[
                        {"id": t, "does": TEMPLATES[t][1], "values": TEMPLATES[t][2]} for t in allowed
                    ],
                    rejected=list(rejected),
                    namespace=ctx.namespace,
                )
            except (LLMUnavailable, ValueError):
                return None  # no usable answer: the rules decide
            if answer.template == "none":
                note = (
                    f"No write: the LLM found no safe fix in the evidence ({answer.rationale.strip()[:300]})."
                )
                return FixOutcome(None, "none", note, lookups)
            action, reason = self._build(answer, top, ctx, allowed, grounding, {e["id"] for e in shown})
            if action is not None and action.command in blocked:
                action, reason = None, "M3 already blocked this exact command"
            if action is not None:
                return FixOutcome(action, "llm", "", lookups)
            rejected.append(
                f"{answer.template} target={answer.target} var={answer.var} value={answer.value}: {reason}"
            )
        return None  # every try was rejected: the rules decide

    def _lookups(self, top: HypothesisSpec, ctx: DiagContext) -> list[Evidence]:
        """Extra read-only facts a fix needs: the service list, where an address's name and port live."""
        if top.layer != "app-config":
            return []
        command = f"kubectl get services -n {ctx.namespace}"
        result = guarded_run(self.reads, command)
        return [Evidence(id="L1", hyp_id=top.id, command=command, output=result.output, ok=result.ok)]

    def _build(self, answer, top, ctx, allowed, grounding, evidence_ids) -> tuple[ProposedAction | None, str]:
        """The exact command for the LLM's choice, or why it can't be used."""
        if answer.template not in allowed:
            return None, f"template {answer.template} does not fix a {top.layer} fault"
        target = answer.target.strip()
        if not SERVICE_NAME.fullmatch(target):
            return None, f"target {target!r} is not a deployment name"
        if not set(answer.cited) <= evidence_ids:
            return None, f"cites evidence that does not exist: {sorted(set(answer.cited) - evidence_ids)}"
        if top.layer == "dependency":
            if not _appears(target, grounding["values"]) and target != top.component:
                return None, f"target {target} appears in no read's output"
        elif target != top.component:
            return None, f"target must be the diagnosed component {top.component}"

        if answer.template == "restart":
            return _action(restart_command(target, ctx.namespace), ctx, answer, top), ""

        var, value = answer.var.strip(), answer.value.strip()
        if not ENV_VAR.fullmatch(var) or not _appears(var, grounding["names"]):
            return None, f"env var {var!r} is not named in the evidence"
        if not SAFE_VALUE.fullmatch(value):
            return None, f"value {value!r} has characters a plain address never needs"
        missing = [part for part in value.split(":") if part and not _appears(part, grounding["values"])]
        if missing:
            return None, f"value part(s) {missing} appear in no read's output: never guess a value"
        host = value.split(":")[0]
        unreachable = _unreachable(top.component, ctx.symptoms)
        if unreachable and not any(_same_service(name, host) for name in unreachable):
            # Name the service in the reason: the retry needs to know where to look, not only what was wrong.
            return None, (
                f"host {host} is not the service {top.component}'s error says it cannot reach "
                f"({', '.join(unreachable)}); use that service's full NAME and port from the service list"
            )
        if host == target:
            return (
                None,
                f"the address points {target} at itself; it must name the service {target} cannot reach",
            )
        if not answer.cited:
            return None, "a value must cite the evidence that shows it"
        return _action(patch_env_command(target, var, value, ctx.namespace), ctx, answer, top), ""

    # ---------- full volume: a recommendation for a person ----------

    def _storage_handoff(self, top: HypothesisSpec, ctx: DiagContext) -> FixOutcome:
        """No write. Reads which PVC the deployment mounts and its size, and recommends doubling it."""
        ns = ctx.namespace
        command = f"kubectl get deployment {top.component} -n {ns} -o json"
        result = guarded_run(self.reads, command)
        lookups = [Evidence(id="L1", hyp_id=top.id, command=command, output=result.output, ok=result.ok)]
        claim = _claim_name(result.output) if result.ok else None
        size, storage_class = None, None
        if claim is not None:
            command = f"kubectl get pvc {claim} -n {ns} -o json"
            result = guarded_run(self.reads, command)
            lookups.append(
                Evidence(id="L2", hyp_id=top.id, command=command, output=result.output, ok=result.ok)
            )
            if result.ok:
                size, storage_class = _pvc_size(result.output)

        note = (
            f"human_action_required: {top.component}'s data volume is full. No write M3 can check frees "
            "disk space (a restart crashes again on the same full volume; deleting the PVC loses the data), "
            "so M2 proposes no write. Recommended for a person: "
        )
        if claim is None:
            note += f"expand the PVC that {top.component} mounts, or free space on it."
            return FixOutcome(None, "none", note, lookups)
        bigger = _doubled(size) if size else None
        request = {"storage": bigger or "<larger size>"}
        patch = json.dumps({"spec": {"resources": {"requests": request}}}, separators=(",", ":"))
        note += f"expand PVC {claim}" + (f" from {size} to {bigger}" if bigger else "")
        note += f": `kubectl patch pvc {claim} -n {ns} -p '{patch}'`"
        if storage_class:
            note += f" (storage class {storage_class} must allow volume expansion)"
        note += ", then let the pod restart; or free space on the volume."
        return FixOutcome(None, "none", note, lookups)

    # ---------- the rule fallback ----------

    def _rules(self, top: HypothesisSpec, ctx: DiagContext, blocked: dict[str, SafetyVerdict]) -> FixOutcome:
        fix = propose_fix(top, ctx)
        if fix is None:
            return FixOutcome(None, "none")
        if fix.command in blocked:  # M3 proved this unsafe; the rules know one fix per fault
            return FixOutcome(None, "none", blocked_note(blocked[fix.command]))
        return FixOutcome(fix, "rules")


def _claim_name(deployment_json: str) -> str | None:
    """The first PVC the deployment's pods mount (`spec.template.spec.volumes[].persistentVolumeClaim`)."""
    try:
        volumes = json.loads(deployment_json)["spec"]["template"]["spec"].get("volumes", [])
        for volume in volumes:
            claim = (volume.get("persistentVolumeClaim") or {}).get("claimName")
            if claim and SERVICE_NAME.fullmatch(claim):
                return claim
    except (ValueError, KeyError, TypeError, AttributeError):
        pass  # not JSON, or not shaped like a deployment
    return None


def _pvc_size(pvc_json: str) -> tuple[str | None, str | None]:
    """(capacity, storage class) of a `kubectl get pvc -o json`; capacity falls back to the request."""
    try:
        pvc = json.loads(pvc_json)
        size = pvc.get("status", {}).get("capacity", {}).get("storage")
        size = size or pvc["spec"].get("resources", {}).get("requests", {}).get("storage")
        return size, pvc["spec"].get("storageClassName")
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, None


def _doubled(size: str) -> str | None:
    """'1Gi' -> '2Gi'; None for a size written any other way."""
    match = SIZE.fullmatch(size)
    return f"{int(match.group(1)) * 2}{match.group(2)}" if match else None


def _unreachable(component: str, symptoms: list[str]) -> list[str]:
    """Services the component's own error lines say it fails to reach ("failed to connect to redis")."""
    names = [n for line in symptoms if line.startswith(f"{component}:") for n in NAMED_SERVICE.findall(line)]
    return list(dict.fromkeys(n for n in names if n not in NOT_A_SERVICE and n != component))


def _same_service(name: str, host: str) -> bool:
    """A log's short name and a Service's full name: 'redis' matches 'redis' and 'redis-cart'."""
    return host == name or host.startswith(f"{name}-") or host.endswith(f"-{name}")


def _appears(word: str, text: str) -> bool:
    """`word` occurs in `text` on its own, not inside a longer name ("redis" is not in "redis-cart")."""
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text) is not None


def _action(command: str, ctx: DiagContext, answer: FixAnswer, top: HypothesisSpec) -> ProposedAction:
    cited = f" [evidence: {', '.join(answer.cited)}]" if answer.cited else ""
    return ProposedAction(
        command=command,
        is_write=True,
        target_namespace=ctx.namespace,
        rationale=f"{answer.rationale.strip()[:300]}{cited} ({top.label()})",
    )
