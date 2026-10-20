"""M2's internal data. Only service.py converts these to the shared contracts."""

from typing import Literal

from pydantic import BaseModel, Field

# The LLM picks one of these words; belief.LAMBDA turns it into a number. It never gives a probability.
Verdict = Literal["strong-support", "weak-support", "neutral", "weak-refute", "strong-refute"]


Role = Literal["origin", "upstream", "quiet-dependency", "top-signals", "has-signals", "other"]


class Candidate(BaseModel):
    """A component that could hold the root cause, with its graph prior g(component).

    `role` and `hops` say why it is suspected, so the LLM prompt and the report can explain the weight:
    origin = deepest failing service (hops 0), upstream = a caller on the failing path (hops up from
    the origin, None if the walk can't reach it), quiet-dependency = something the origin calls or
    names in its errors that reports nothing itself (hops 1). Without a graph: top-signals / has-signals.
    """

    service: str
    weight: float = 1.0  # see context_adapter: the "almanac" or "hop" scheme
    role: Role = "other"
    hops: int | None = None


class DiagContext(BaseModel):
    """What M2 diagnoses from, adapted out of M1's SemanticContext."""

    namespace: str
    candidates: list[Candidate] = []
    symptoms: list[str] = []
    failing_path: list[str] = []
    node_status: dict[str, str] = {}  # M1's k8s status per service, e.g. "Running", "CrashLoopBackOff"
    notes: str = ""  # M1's notes, e.g. why the context is empty


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
