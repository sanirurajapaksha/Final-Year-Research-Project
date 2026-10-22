"""REPORT step: a short explanation of the diagnosis for the person reading the dashboard.

The answer is already decided (belief maths) and so is the fix (fix step); the LLM only says it in
plain words. So it gets the facts and may add nothing:
  - at most 120 words: where the fault is, what it is, what it affects, and what M2 proposes;
  - every claim cites the evidence ids it rests on (E1, L1, ...), and code checks that each id the
    text mentions is a read that succeeded, so the text can't point at a read that never happened
    or present a failed read ("no data") as a finding ("the service is down");
  - when the loop did not confirm the top hypothesis, the text must say it is unconfirmed.
If the LLM is unavailable or its text fails a check, a fixed template sentence is used, built from the
same facts. Either way the report never changes the diagnosis or the actions.
"""

import re

from pydantic import BaseModel

from argus.contracts import ProposedAction
from argus.diagnosis.core.models import DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.ports.base import LLMClient, LLMUnavailable
from argus.diagnosis.ports.fakes import NoLLM

MAX_WORDS = 120
EVIDENCE_ID = re.compile(r"\b[ELS]\d+\b")
UNCONFIRMED_WORDS = ("unconfirmed", "not confirmed", "could not confirm", "did not confirm")


class ReportAnswer(BaseModel):
    text: str
    cited: list[str]


class ReportWriter:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or NoLLM()

    def write(
        self,
        top: HypothesisSpec,
        probability: float,
        confirmed: bool,
        stop_reason: str,
        evidence: list[Evidence],
        verdicts: dict[str, str],
        fix: ProposedAction | None,
        note: str,
        ctx: DiagContext,
    ) -> tuple[str, str]:
        """(report text, "llm" or "template")."""
        facts = _facts(top, probability, confirmed, stop_reason, evidence, verdicts, fix, note)
        if not isinstance(self.llm, NoLLM):
            try:
                answer = self.llm.structured(
                    "report",
                    ReportAnswer,
                    facts=facts,
                    # Only reads that returned something: a failed read is "no data", never "the service
                    # is down" (deepseek-v4-flash cited one that way on its first end-to-end run).
                    evidence=[
                        {"id": e.id, "command": e.command, "output": e.output} for e in evidence if e.ok
                    ],
                    signals=list(ctx.symptoms),
                    confirmed=confirmed,
                )
                text = " ".join(answer.text.split())
                citable = {e.id for e in evidence if e.ok} | {"S1"}
                if _usable(text, answer.cited, citable, top, confirmed):
                    return text, "llm"
            except (LLMUnavailable, ValueError):
                pass
        return _template(top, probability, confirmed, stop_reason, evidence, verdicts, fix, note), "template"


def top_verdicts(history: list[dict], hyp_id: str) -> dict[str, str]:
    """Evidence id -> the verdict it gave the given hypothesis (only reads that judged it)."""
    out: dict[str, str] = {}
    for step in history:
        if step.get("event") == "update" and hyp_id in step.get("verdicts", {}):
            out[step["evidence"]] = step["verdicts"][hyp_id]
    return out


def _facts(top, probability, confirmed, stop_reason, evidence, verdicts, fix, note) -> list[str]:
    lines = [
        f"Diagnosis: {top.label()}",
        f"Belief: {probability:.0%}; stop reason: {stop_reason}; "
        + ("confirmed by the reads" if confirmed else "NOT confirmed by the reads"),
    ]
    for e in evidence:
        judged = f" -> {verdicts[e.id]} for this diagnosis" if e.id in verdicts else ""
        if e.ok:
            lines.append(f"{e.id}: {e.command} (ok){judged}")
        else:
            lines.append(
                f"{e.id}: {e.command} (FAILED: it returned nothing, so it is not evidence; do not cite it)"
            )
    if fix is not None:
        lines.append(f"Proposed fix (M3 checks it before anything runs): {fix.command}")
    elif note:
        lines.append(f"No fix proposed: {note}")
    else:
        lines.append("No fix proposed.")
    return lines


def _usable(text: str, cited: list[str], ids: set[str], top: HypothesisSpec, confirmed: bool) -> bool:
    if not text or len(text.split()) > MAX_WORDS:
        return False
    mentioned = set(EVIDENCE_ID.findall(text)) | set(cited)
    if not mentioned or not mentioned <= ids:
        return False  # it must cite something, and only reads that happened
    if top.component not in text:
        return False
    if not confirmed and not any(w in text.lower() for w in UNCONFIRMED_WORDS):
        return False  # an unconfirmed guess must never read like a finding
    return True


def _template(top, probability, confirmed, stop_reason, evidence, verdicts, fix, note) -> str:
    judged = [f"{e} {v}" for e, v in verdicts.items()]
    reads = f"{len(evidence)} read(s)" + (f" ({', '.join(judged)})" if judged else "")
    if confirmed:
        head = f"Root cause: {top.label()} ({probability:.0%}), confirmed by {reads}."
    else:
        head = (
            f"Unconfirmed: the best guess is {top.label()} ({probability:.0%}) after {reads}; "
            f"stop reason: {stop_reason}."
        )
    if fix is not None:
        tail = f" Proposed fix, to be checked by M3: {fix.command}"
    elif note:
        tail = f" {note}"
    else:
        tail = " No fix proposed."
    return head + tail
