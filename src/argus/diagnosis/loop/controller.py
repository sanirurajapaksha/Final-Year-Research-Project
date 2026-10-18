"""CONTROL step: the diagnosis loop. Plain Python makes every decision; the LLM only fills in data.

DRAFT -> PRIOR -> (PLAN -> EXECUTE -> SCORE -> UPDATE -> DECIDE)* -> REHYPOTHESIZE or finish.
"""

import time
from dataclasses import dataclass, replace

from pydantic import BaseModel

from argus.diagnosis.core.belief import H0, BeliefState
from argus.diagnosis.core.config import DiagnosisConfig
from argus.diagnosis.core.models import DiagContext, DiagnosisReport, Evidence, HypothesisSpec, Verdict
from argus.diagnosis.loop.generator import RuleGenerator
from argus.diagnosis.ports.base import LLMClient, LLMUnavailable, ReadExecutor, guarded_run
from argus.diagnosis.ports.fakes import NoLLM, NullReadExecutor


class ScoreAnswer(BaseModel):
    """The LLM's reading of one piece of evidence: a verdict word per hypothesis id."""

    verdicts: dict[str, Verdict] = {}


@dataclass
class LoopResult:
    belief: BeliefState
    hypotheses: dict[str, HypothesisSpec]
    evidence: list[Evidence]
    report: DiagnosisReport


class Controller:
    def __init__(
        self,
        config: DiagnosisConfig | None = None,
        llm: LLMClient | None = None,
        reads: ReadExecutor | None = None,
        generator=None,
    ) -> None:
        self.cfg = config or DiagnosisConfig()
        self.llm = llm or NoLLM()
        self.reads = reads or NullReadExecutor()
        self.generator = generator or RuleGenerator()

    def run(self, ctx: DiagContext) -> LoopResult:
        cfg = self.cfg
        params = cfg.params if cfg.use_h0 else replace(cfg.params, pi0=0.0)
        bs = BeliefState(params=params)
        hyps: dict[str, HypothesisSpec] = {}
        evidence: list[Evidence] = []
        tested: set[str] = set()
        rehyps = 0
        deadline = time.monotonic() + cfg.wall_clock_s

        def finish(reason: str, low: bool = False) -> LoopResult:
            report = DiagnosisReport(stop_reason=reason, low_confidence=low, usage=dict(self.llm.usage))
            return LoopResult(bs, hyps, evidence, report)

        # DRAFT + PRIOR
        first = self._draft(ctx, hyps)
        if not first:
            return finish("no hypotheses: " + (ctx.notes or "no candidates"), low=True)
        bs.init({h.id: self._prior(h, ctx) for h in first})

        while True:
            # PLAN: untested hypotheses still in play, highest belief first
            untested = [h for h, _ in bs.ranked() if h in bs.active() and h not in tested]
            if untested:
                if len(evidence) >= cfg.max_reads or time.monotonic() > deadline:
                    return finish("budget", low=True)
                hyp = hyps[untested[0]]
                tested.add(hyp.id)
                evidence.append(self._execute(hyp, f"E{len(evidence) + 1}"))  # EXECUTE
                bs.update(self._score(evidence[-1], bs, hyps), evidence[-1].id)  # SCORE + UPDATE
                decision = bs.decide()  # DECIDE
                if decision == "stop":
                    return finish("confident")
                # A low belief with rivals still untested just means we haven't looked yet;
                # only H0 leading means the evidence points outside this round's hypotheses.
                if decision == "continue" or bs.ranked()[0][0] != H0:
                    continue
            # REHYPOTHESIZE: H0 leads, or nothing left to test
            if not cfg.backtracking or rehyps >= cfg.max_rehyp:
                return finish("out of hypotheses", low=True)
            new = self._draft(ctx, hyps)
            if not new:
                return finish("out of hypotheses", low=True)
            bs.add_hypotheses([h.id for h in new])
            rehyps += 1

    def _draft(self, ctx: DiagContext, hyps: dict[str, HypothesisSpec]) -> list[HypothesisSpec]:
        """New hypotheses that repeat nothing already tried; ids carry on from the last round."""
        tried = {(h.component, h.fault) for h in hyps.values()}
        new = self.generator.draft(ctx, self.cfg.k, tried, next_id=len(hyps) + 1)
        hyps.update({h.id: h for h in new})
        return new

    def _prior(self, hyp: HypothesisSpec, ctx: DiagContext) -> float:
        """c(confidence) x g(component): the graph prior only when graph_priors is on."""
        weight = {c.service: c.weight for c in ctx.candidates}.get(hyp.component, 1.0)
        return max(hyp.confidence, 0.01) * (weight if self.cfg.graph_priors else 1.0)

    def _execute(self, hyp: HypothesisSpec, evidence_id: str) -> Evidence:
        result = guarded_run(self.reads, hyp.test)
        return Evidence(
            id=evidence_id,
            hyp_id=hyp.id,
            command=hyp.test,
            output=result.output[: self.cfg.max_output_chars],
            ok=result.ok,
        )

    def _score(self, ev: Evidence, bs: BeliefState, hyps: dict[str, HypothesisSpec]) -> dict[str, str]:
        """Verdict per active hypothesis. A failed read or no/invalid LLM answer is all neutral."""
        if not ev.ok:
            return {}
        active = bs.active()
        try:
            answer = self.llm.structured(
                "score",
                ScoreAnswer,
                command=ev.command,
                output=ev.output,
                hypotheses={h: f"{hyps[h].label()} | expects: {hyps[h].expected}" for h in active},
            )
        except (LLMUnavailable, ValueError):  # pydantic's ValidationError is a ValueError
            return {}
        return {h: v for h, v in answer.verdicts.items() if h in active}  # invented ids ignored
