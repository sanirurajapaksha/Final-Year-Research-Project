"""DRAFT step with the LLM: rival hypotheses written from M1's actual error text.

The rule table only knows three faults; the LLM can read any wording ("dial tcp: lookup redis-cart:
no such host") and propose the matching fault and check. It only proposes:
  - its confidence is a word (high / medium / low), turned into c(h) here; it never gives a number;
  - every hypothesis goes through the same validate() as the rules (known component, read-only test,
    not already refuted), and ids are assigned by M2;
  - the candidates' hop roles are shown to it, but their weights are applied in code (the graph prior),
    and the prompt tells it not to judge by position, so position is not counted twice.
If the LLM is unavailable or its answer is unusable, the rule generator drafts instead; if it gives
fewer than k usable hypotheses, the rule generator fills the round.
"""

from typing import Literal

from pydantic import BaseModel

from argus.diagnosis.core.models import DiagContext, HypothesisSpec
from argus.diagnosis.loop.generator import RuleGenerator, validate
from argus.diagnosis.ports.base import LLMClient, LLMUnavailable
from argus.diagnosis.prompts import LAYERS

# The Almanac's c(h) for the generator's confidence words.
CONFIDENCE = {"high": 0.5, "medium": 0.3, "low": 0.2}


class DraftItem(BaseModel):
    component: str
    layer: Literal[LAYERS]
    fault: str
    test: str
    expected: str
    confidence: Literal["high", "medium", "low"]


class DraftAnswer(BaseModel):
    hypotheses: list[DraftItem] = []


class LLMGenerator:
    def __init__(
        self, llm: LLMClient, fallback: RuleGenerator | None = None, per_component: int | None = None
    ):
        self.llm = llm
        self.fallback = fallback or RuleGenerator(per_component=per_component)
        self.per_component = per_component

    def draft(
        self,
        ctx: DiagContext,
        k: int,
        refuted: set[tuple[str, str]] = frozenset(),
        next_id: int = 1,
    ) -> list[HypothesisSpec]:
        try:
            answer = self.llm.structured(
                "draft",
                DraftAnswer,
                candidates=[c.model_dump() for c in ctx.candidates],
                failing_path=list(ctx.failing_path),
                signals=list(ctx.symptoms),
                pod_status=dict(ctx.node_status),
                refuted=[f"{c}: {what}" for c, what in sorted(refuted) if what not in LAYERS],
                k=k,
                namespace=ctx.namespace,
            )
        except (LLMUnavailable, ValueError):  # no LLM, or a reply that doesn't fit DraftAnswer
            return self.fallback.draft(ctx, k, refuted, next_id)

        specs = [
            HypothesisSpec(
                component=item.component.strip(),
                layer=item.layer,
                fault=item.fault.strip(),
                test=item.test.strip(),
                expected=item.expected.strip(),
                confidence=CONFIDENCE[item.confidence],
                source="llm",
            )
            for item in answer.hypotheses
        ]
        kept = validate(specs, ctx, refuted, k, next_id, self.per_component)
        if len(kept) < k:  # fill the round from the rules, never repeating a component + layer pair
            mine = {(h.component, h.fault) for h in kept} | {(h.component, h.layer) for h in kept}
            extra = self.fallback.draft(ctx, k, set(refuted) | mine, next_id)
            kept += extra[: k - len(kept)]
        return [h.model_copy(update={"id": f"H{next_id + i}"}) for i, h in enumerate(kept)]
