"""M2's internal data. Only service.py converts these to the shared contracts."""

from typing import Literal

from pydantic import BaseModel, Field

# The LLM picks one of these words; belief.LAMBDA turns it into a number. It never gives a probability.
Verdict = Literal["strong-support", "weak-support", "neutral", "weak-refute", "strong-refute"]


class Candidate(BaseModel):
    """A component that could hold the root cause, with its graph prior g(component)."""

    service: str
    weight: float = 1.0  # 1.5 deepest failing service, 1.0 on the failing path, 0.5 otherwise


class DiagContext(BaseModel):
    """What M2 diagnoses from, adapted out of M1's SemanticContext."""

    namespace: str
    candidates: list[Candidate] = []
    symptoms: list[str] = []
    failing_path: list[str] = []


class HypothesisSpec(BaseModel):
    """One rival explanation plus the read that can confirm or refute it."""

    id: str = ""  # set by M2 (H1, H2, ...), never taken from the LLM
    component: str
    layer: str  # e.g. "k8s-network", "app-config", "resources"
    fault: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    test: str  # one kubectl read; must pass is_read_only
    expected: str = ""  # what the test shows if this hypothesis is true

    def label(self) -> str:
        return f"{self.component} [{self.layer}] {self.fault}"


class Evidence(BaseModel):
    """The result of one executed read, cited as E1, E2, ..."""

    id: str
    hyp_id: str
    command: str
    output: str
    ok: bool


class DiagnosisReport(BaseModel):
    """Run details with no contract field yet (team question Q4); used by experiments."""

    stop_reason: str = ""
    low_confidence: bool = False
    report_text: str = ""
    usage: dict[str, int] = {}