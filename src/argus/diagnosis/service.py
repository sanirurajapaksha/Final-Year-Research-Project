"""M2 entry point: SemanticContext -> DiagnosisResult.

`diagnose()` keeps its signature so M4's pipeline doesn't change. A `Diagnoser` is one session per
incident: it keeps the last run, so M3's feedback is answered without running the reads again.
"""

from argus.contracts import DiagnosisResult, Hypothesis, SafetyVerdict, SemanticContext
from argus.diagnosis.core.belief import H0
from argus.diagnosis.core.config import DiagnosisConfig
from argus.diagnosis.core.models import DiagnosisReport
from argus.diagnosis.loop.context_adapter import adapt
from argus.diagnosis.loop.controller import Controller, LoopResult
from argus.diagnosis.ports.base import LLMClient, ReadExecutor

CITE_CHARS = 200  # tool output kept per citation


class Diagnoser:
    def __init__(
        self,
        config: DiagnosisConfig | None = None,
        llm: LLMClient | None = None,
        reads: ReadExecutor | None = None,
    ) -> None:
        self.config = config or DiagnosisConfig()
        self.controller = Controller(self.config, llm, reads)
        self.last: LoopResult | None = None
        self.report: DiagnosisReport | None = None  # stop_reason, low_confidence, usage: for experiments

    def diagnose(self, context: SemanticContext, feedback: list[SafetyVerdict] | None = None) -> DiagnosisResult:
        if feedback and self.last is not None:
            # No write proposer yet (step 7), so a BLOCK can't be revised: keep the diagnosis,
            # propose nothing, and say why. The reads are not run again.
            blocked = "; ".join(v.command for v in feedback)
            text = f"blocked by M3: {blocked}. No alternative proposer yet: mitigation needs a human."
            self.report = self.last.report.model_copy(update={"report_text": text})
            return to_result(self.last)
        self.last = self.controller.run(adapt(context, self.config.namespace))
        self.report = self.last.report
        return to_result(self.last)


def to_result(run: LoopResult) -> DiagnosisResult:
    """Every hypothesis ranked by belief, H0 included, so the probabilities sum to 1.
    No actions: the reads already ran inside the loop, and writes come with the proposer."""
    if not run.belief.belief:
        reason = run.report.stop_reason
        return DiagnosisResult(hypotheses=[Hypothesis(root_cause=f"{H0}: no diagnosis ({reason})", probability=1.0)])
    cites = _citations(run)
    return DiagnosisResult(
        hypotheses=[
            Hypothesis(root_cause=_root_cause(h, run), probability=min(max(p, 0.0), 1.0), evidence=cites.get(h, []))
            for h, p in run.belief.ranked()
        ]
    )


def _root_cause(h: str, run: LoopResult) -> str:
    if h == H0:
        return f"{H0}: none of the listed hypotheses"
    return f"{h}: {run.hypotheses[h].label()}"


def _citations(run: LoopResult) -> dict[str, list[str]]:
    """Hypothesis id -> the evidence that moved it, e.g. 'E1 strong-support kubectl ...: <output>'."""
    evidence = {e.id: e for e in run.evidence}
    cites: dict[str, list[str]] = {}
    for step in run.belief.history:
        for h, verdict in step.get("verdicts", {}).items():
            e = evidence[step["evidence"]]
            cites.setdefault(h, []).append(f"{e.id} {verdict} {e.command}: {e.output[:CITE_CHARS]}")
    return cites


_session: Diagnoser | None = None


def diagnose(context: SemanticContext, feedback: list[SafetyVerdict] | None = None) -> DiagnosisResult:
    """Rank root-cause hypotheses (H0 included) for the incident in `context`.

    No feedback starts a new session; feedback goes to the last one. This process-level session
    is a stopgap until the pipeline owns sessions (team question Q2).
    """
    global _session
    if feedback is None or _session is None:
        _session = Diagnoser()
    return _session.diagnose(context, feedback)