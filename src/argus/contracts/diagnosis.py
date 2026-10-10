"""M2's output: hypotheses about the root cause and the actions it wants to run."""

from pydantic import BaseModel, Field


class Hypothesis(BaseModel):
    root_cause: str
    probability: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = []


class ProposedAction(BaseModel):
    """One command M2 wants to run.

    `command` is byte-exact: no module may compress, trim or rewrite it, because M3 must
    check exactly the string that will execute.
    """

    command: str
    is_write: bool
    target_namespace: str | None = None
    rationale: str = ""


class DiagnosisResult(BaseModel):
    hypotheses: list[Hypothesis] = []
    actions: list[ProposedAction] = []
