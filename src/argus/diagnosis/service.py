"""M2 entry point: M1's SemanticContext in, ranked hypotheses and proposed actions out.

diagnose() is the only place M2's internal models are turned into the shared contracts:
ADAPT (context_adapter) -> loop (controller) -> convert (this file).
diagnose_report() runs the same thing and returns plain data for the dashboard.
"""

import json

from argus.config import load_settings
from argus.contracts import (
    DiagnosisResult,
    GateDecision,
    Hypothesis,
    ProposedAction,
    SafetyVerdict,
    SemanticContext,
)
from argus.diagnosis.core.belief import H0
from argus.diagnosis.core.config import DiagnosisConfig
from argus.diagnosis.core.models import DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.loop.context_adapter import adapt
from argus.diagnosis.loop.controller import Controller, LoopResult
from argus.diagnosis.loop.fixes import propose_fix
from argus.diagnosis.loop.scorer import RuleScorer
from argus.diagnosis.ports.base import LLMClient, ReadExecutor
from argus.diagnosis.ports.openrouter import llm_from_env

EVIDENCE_CHARS = 200  # how much of each read's output a hypothesis carries as evidence


def diagnose(
    context: SemanticContext,
    feedback: list[SafetyVerdict] | None = None,
    *,
    config: DiagnosisConfig | None = None,
    llm: LLMClient | None = None,
    reads: ReadExecutor | None = None,
) -> DiagnosisResult:
    """Rank root-cause hypotheses and propose the next actions.

    `feedback` carries M3's BLOCK verdicts (with counterexamples) from the previous round.
    M2 never proposes a blocked command again; when it has no other safe fix, it says why
    in the top hypothesis's evidence instead.

    The keyword-only arguments are for tests and the demo. M4 calls diagnose(context) and
    diagnose(context, feedback=...): the LLM is then the team's model when ARGUS_LLM_API_KEY and
    ARGUS_LLM_MODEL are set, and rules otherwise; with no cluster every read is neutral.
    """
    ctx, result = _run(context, config, llm, reads)
    return to_result(result, ctx, blocked_verdicts(feedback))


def diagnose_report(
    context: SemanticContext,
    feedback: list[SafetyVerdict] | None = None,
    *,
    config: DiagnosisConfig | None = None,
    llm: LLMClient | None = None,
    reads: ReadExecutor | None = None,
) -> dict:
    """The same run as diagnose(), as plain data the dashboard can show and a test can check."""
    ctx, result = _run(context, config, llm, reads)
    diagnosis = to_result(result, ctx, blocked_verdicts(feedback))
    return {
        "namespace": ctx.namespace,
        "candidates": [{"service": c.service, "weight": c.weight} for c in ctx.candidates],
        "hypotheses": _hypothesis_rows(result),
        "reads": [
            {"id": e.id, "hypothesis": e.hyp_id, "command": e.command, "ok": e.ok, "output": e.output}
            for e in result.evidence
        ],
        "belief_rounds": _belief_rounds(result),
        "stop_reason": result.report.stop_reason,
        "low_confidence": result.report.low_confidence,
        "diagnosis": diagnosis.model_dump(),
    }


def _run(
    context: SemanticContext,
    config: DiagnosisConfig | None,
    llm: LLMClient | None,
    reads: ReadExecutor | None,
) -> tuple[DiagContext, LoopResult]:
    cfg = config or DiagnosisConfig()
    ctx = adapt(context, cfg.namespace, scheme="hop" if cfg.graph_priors == "hop" else "almanac")
    if llm is None:  # M4's plain diagnose(context): the team's model when a key is set, else rules
        llm = llm_from_env(load_settings().llm_model)
    controller = Controller(cfg, llm=llm, reads=reads, scorer=RuleScorer())
    return ctx, controller.run(ctx)


def to_result(result: LoopResult, ctx: DiagContext, blocked: dict[str, SafetyVerdict]) -> DiagnosisResult:
    """Turn the loop's belief state into the contract: hypotheses best first, then actions."""
    ranked = [(h, p) for h, p in result.belief.ranked() if h != H0]
    hypotheses = [
        Hypothesis(
            root_cause=result.hypotheses[h].label(),
            probability=round(p, 4),
            evidence=_evidence_lines(h, result.evidence),
        )
        for h, p in ranked
    ]
    actions: list[ProposedAction] = []
    if ranked:
        top = result.hypotheses[ranked[0][0]]
        actions.append(_read_action(top, ctx.namespace))
        fix = propose_fix(top, ctx)
        if not confirmed(result):
            # Test before acting: the reads never confirmed `top`, so M2 proposes only the read
            # that would, and no write M3 might approve. The reason goes where the dashboard shows it.
            hypotheses[0].evidence.append(_unconfirmed_line(result))
        elif fix is not None and fix.command in blocked:
            # M3 proved this fix unsafe. M2 knows one fix per fault, so it proposes no other
            # write and records why, with M3's counterexample, where the dashboard shows it.
            hypotheses[0].evidence.append(_blocked_line(blocked[fix.command]))
        elif fix is not None:
            actions.append(fix)
    kept = [a for a in actions if a.command not in blocked]
    return DiagnosisResult(hypotheses=hypotheses, actions=kept)


def confirmed(result: LoopResult) -> bool:
    """The loop stopped because one real hypothesis clearly beat the others and H0 ("none of these").

    Only then may M2 propose a write. Running out of hypotheses or budget, or every read failing,
    ends with low confidence: the top hypothesis is then just the least-refuted guess.
    """
    return result.report.stop_reason == "confident" and not result.report.low_confidence


def _unconfirmed_line(result: LoopResult) -> str:
    """Why there is no write: the loop stopped without confirming the top hypothesis."""
    return (
        f"No write: the reads did not confirm this hypothesis (stop reason: {result.report.stop_reason}), "
        "so M2 proposes only the read that would check it."
    )


def blocked_verdicts(feedback: list[SafetyVerdict] | None) -> dict[str, SafetyVerdict]:
    """M3's BLOCK verdicts from last round, by command. Compared byte-exact, as M3 checked them."""
    blocked: dict[str, SafetyVerdict] = {}
    for verdict in feedback or []:
        if verdict.decision == GateDecision.BLOCK:
            blocked[verdict.command] = verdict
    return blocked


def _blocked_line(verdict: SafetyVerdict) -> str:
    """Why the fix was dropped: M3's reason and counterexample, and that no other write follows."""
    line = f"M3 blocked the fix `{verdict.command}`: {verdict.reason}"
    if verdict.counterexample:
        line += f"; counterexample: {json.dumps(verdict.counterexample, sort_keys=True)}"
    return line + ". M2 knows no other safe fix for this fault, so it proposes no write."


def _read_action(top: HypothesisSpec, namespace: str) -> ProposedAction:
    """The read that confirms the top hypothesis, so M4 can show or re-run it."""
    return ProposedAction(
        command=top.test,
        is_write=False,
        target_namespace=namespace,
        rationale=f"check {top.label()}: expect {top.expected}",
    )


def _evidence_lines(hyp_id: str, evidence: list[Evidence]) -> list[str]:
    """One line per read run for this hypothesis: E1: command -> start of the output."""
    lines: list[str] = []
    for e in evidence:
        if e.hyp_id != hyp_id:
            continue
        status = "ok" if e.ok else "failed"
        lines.append(f"{e.id} ({status}): {e.command} -> {e.output[:EVIDENCE_CHARS]}")
    return lines


def _hypothesis_rows(result: LoopResult) -> list[dict]:
    """Every hypothesis, best first, with its final belief and whether it was pruned."""
    rows: list[dict] = []
    for h, p in result.belief.ranked():
        if h == H0:
            continue
        spec = result.hypotheses[h]
        rows.append(
            {
                "id": h,
                "component": spec.component,
                "layer": spec.layer,
                "fault": spec.fault,
                "probability": round(p, 4),
                "status": result.belief.status.get(h, "active"),
                "test": spec.test,
                "expected": spec.expected,
                "source": spec.source,
            }
        )
    return rows


def _belief_rounds(result: LoopResult) -> list[dict]:
    """The belief after each step of the loop: start, every read, every new round of hypotheses."""
    rounds: list[dict] = []
    for i, step in enumerate(result.belief.history):
        rounds.append(
            {
                "step": i,
                "event": step["event"],
                "evidence": step.get("evidence", ""),
                "verdicts": step.get("verdicts", {}),
                "belief": {h: round(p, 4) for h, p in step["belief"].items()},
            }
        )
    return rounds
