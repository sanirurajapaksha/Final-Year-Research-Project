"""M2 entry point: M1's SemanticContext in, ranked hypotheses and proposed actions out.

diagnose() is the only place M2's internal models are turned into the shared contracts:
ADAPT (context_adapter) -> loop (controller) -> convert (this file).
diagnose_report() runs the same thing and returns plain data for the dashboard.
"""

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
from argus.diagnosis.loop.llm_fixer import FixProposer
from argus.diagnosis.loop.report import ReportWriter, top_verdicts
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
    diagnose(context, feedback=...): M2 then runs on its rules, and uses the team's model only when
    ARGUS_M2_USE_LLM is on and ARGUS_LLM_API_KEY / ARGUS_LLM_MODEL are set (opt-in, because those two
    are shared with M3). With no cluster every read is neutral.
    """
    cfg = config or DiagnosisConfig()
    ctx, result, fixer = _run(context, cfg, llm, reads)
    return to_result(result, ctx, blocked_verdicts(feedback), fixer, cfg.tentative_fixes)


def diagnose_report(
    context: SemanticContext,
    feedback: list[SafetyVerdict] | None = None,
    *,
    config: DiagnosisConfig | None = None,
    llm: LLMClient | None = None,
    reads: ReadExecutor | None = None,
) -> dict:
    """The same run as diagnose(), as plain data the dashboard can show and a test can check."""
    cfg = config or DiagnosisConfig()
    ctx, result, fixer = _run(context, cfg, llm, reads)
    diagnosis = to_result(result, ctx, blocked_verdicts(feedback), fixer, cfg.tentative_fixes)
    return {
        "namespace": ctx.namespace,
        "candidates": [
            {"service": c.service, "weight": c.weight, "role": c.role, "hops": c.hops} for c in ctx.candidates
        ],
        "hypotheses": _hypothesis_rows(result),
        "reads": [
            {"id": e.id, "hypothesis": e.hyp_id, "command": e.command, "ok": e.ok, "output": e.output}
            for e in result.evidence
        ],
        "belief_rounds": _belief_rounds(result),
        "stop_reason": result.report.stop_reason,
        "low_confidence": result.report.low_confidence,
        "report_text": result.report.report_text,
        "report_source": result.report.report_source,
        "llm": _llm_summary(fixer.llm),
        "diagnosis": diagnosis.model_dump(),
    }


def _run(
    context: SemanticContext,
    cfg: DiagnosisConfig,
    llm: LLMClient | None,
    reads: ReadExecutor | None,
) -> tuple[DiagContext, LoopResult, FixProposer]:
    ctx = adapt(context, cfg.namespace, scheme="hop" if cfg.graph_priors == "hop" else "almanac")
    if llm is None:  # M4's plain diagnose(context): rules, unless ARGUS_M2_USE_LLM turns the LLM on
        settings = load_settings()
        llm = llm_from_env(settings.llm_model) if settings.m2_use_llm else None
    controller = Controller(cfg, llm=llm, reads=reads, scorer=RuleScorer())
    fixer = FixProposer(controller.llm, controller.reads, cfg.max_revisions)  # same LLM and cluster
    return ctx, controller.run(ctx), fixer


def to_result(
    result: LoopResult,
    ctx: DiagContext,
    blocked: dict[str, SafetyVerdict],
    fixer: FixProposer | None = None,
    tentative: bool = False,
) -> DiagnosisResult:
    """Turn the loop's belief state into the contract: hypotheses best first, then actions.

    With `tentative` (DiagnosisConfig.tentative_fixes), an unconfirmed top hypothesis still gets its fix,
    labelled TENTATIVE in its rationale, when it beats H0 and holds at least rho: then M3 checks it.
    """
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
        fixer = fixer or FixProposer()
        fix, note, lookups = None, "", []
        if not confirmed(result):
            # Test before acting: the reads never confirmed `top`, so M2 proposes only the read
            # that would, and no write M3 might approve. The reason goes where the dashboard shows it.
            note = _unconfirmed_line(result)
            if tentative and worth_a_tentative_fix(result):
                # Unless tentative fixes are on: then the same fix a confirmation would give goes to M3,
                # labelled, so the safety layer and M4 still run. M3 checks it exactly like any other.
                outcome = fixer.propose(top, ctx, result.evidence, blocked)
                lookups = outcome.lookups
                hypotheses[0].evidence.extend(_evidence_lines(top.id, lookups))
                if outcome.action is not None:
                    fix = _labelled_tentative(outcome.action, ranked[0][1])
                    actions.append(fix)
                    note = _tentative_line(result)
                elif outcome.note:
                    note += f" No tentative fix either: {outcome.note}"
            hypotheses[0].evidence.append(note)
        else:
            # The LLM picks a fix template and its values from the evidence (rules without an LLM);
            # anything M3 blocked last round is never proposed again. The reason for no write, and
            # any extra read the fix needed, go where the dashboard shows them.
            outcome = fixer.propose(top, ctx, result.evidence, blocked)
            fix, note, lookups = outcome.action, outcome.note, outcome.lookups
            hypotheses[0].evidence.extend(_evidence_lines(top.id, lookups))
            if fix is not None:
                actions.append(fix)
            elif note:
                hypotheses[0].evidence.append(note)
        # REPORT: the decided diagnosis and fix in plain words, first in the top hypothesis's evidence.
        text, source = ReportWriter(fixer.llm).write(
            top,
            ranked[0][1],
            confirmed(result),
            result.report.stop_reason,
            [*result.evidence, *lookups],
            top_verdicts(result.belief.history, top.id),
            fix,
            note,
            ctx,
        )
        result.report.report_text, result.report.report_source = text, source
        hypotheses[0].evidence.insert(0, f"Report ({source}): {text}")
    kept = [a for a in actions if a.command not in blocked]
    return DiagnosisResult(hypotheses=hypotheses, actions=kept)


def confirmed(result: LoopResult) -> bool:
    """The loop stopped because one real hypothesis clearly beat the others and H0 ("none of these").

    Only then may M2 propose a write. Running out of hypotheses or budget, or every read failing,
    ends with low confidence: the top hypothesis is then just the least-refuted guess.
    """
    return result.report.stop_reason == "confident" and not result.report.low_confidence


def worth_a_tentative_fix(result: LoopResult) -> bool:
    """The top hypothesis beats H0 ("none of these") and holds at least rho, the belief below which
    the loop itself drafts new hypotheses. A guess the reads nearly ruled out gets no fix."""
    ranked = [(h, p) for h, p in result.belief.ranked() if h != H0]
    if not ranked:
        return False
    top = ranked[0][1]
    return top > result.belief.belief.get(H0, 0.0) and top >= result.belief.params.rho


def _labelled_tentative(action: ProposedAction, probability: float) -> ProposedAction:
    """The fix with TENTATIVE first in its rationale: a free-text contract field, so it reaches M3 and M4."""
    label = f"TENTATIVE (unconfirmed, {probability:.0%}): "
    return action.model_copy(update={"rationale": label + action.rationale})


def _tentative_line(result: LoopResult) -> str:
    """Why a write goes out although nothing confirmed the hypothesis."""
    return (
        "Tentative fix: the reads did not confirm this hypothesis "
        f"(stop reason: {result.report.stop_reason}), but tentative fixes are on, "
        "so M2 sends its fix to M3 for checking only, labelled TENTATIVE."
    )


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


def _llm_summary(llm) -> dict:
    """Which model ran (None: no LLM, all rules), what it cost, and each call's task and outcome."""
    calls = getattr(llm, "calls", [])
    return {
        "model": getattr(llm, "model", None),
        "usage": dict(getattr(llm, "usage", {})),
        "calls": [
            {"task": c["task"], "prompt_version": c["prompt_version"], "status": c["status"]} for c in calls
        ],
    }


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
