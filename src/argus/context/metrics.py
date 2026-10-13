"""M1 evaluation metrics for a filtering stage.

Two noise-reduction ratios, deliberately kept apart:
- `nrr`: 1 - kept / raw. Simple, but it also rises if real evidence is thrown away.
- `labelled_nrr`: noise pruned / noise in the input, using ground-truth labels.
`false_prune_rate` (evidence pruned / evidence in the input) is the counterweight: report it
next to either NRR, always with the number of scenarios (n).
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from argus.contracts import AnomalySignal

SignalKey = tuple[str, str]


@dataclass(frozen=True)
class StageCounts:
    """How many signals went into a stage and came out, split by ground-truth label."""

    raw: int
    kept: int
    evidence: int
    kept_evidence: int

    def __post_init__(self) -> None:
        if not 0 <= self.kept <= self.raw:
            raise ValueError(f"kept ({self.kept}) must be between 0 and raw ({self.raw})")
        if not 0 <= self.evidence <= self.raw:
            raise ValueError(f"evidence ({self.evidence}) must be between 0 and raw ({self.raw})")
        if not 0 <= self.kept_evidence <= min(self.kept, self.evidence):
            raise ValueError(f"kept_evidence ({self.kept_evidence}) can't exceed kept or evidence")

    @property
    def noise(self) -> int:
        return self.raw - self.evidence

    @property
    def kept_noise(self) -> int:
        return self.kept - self.kept_evidence

    @property
    def nrr(self) -> float:
        """1 - kept / raw."""
        return 1 - _ratio(self.kept, self.raw, "raw")

    @property
    def labelled_nrr(self) -> float:
        """Share of the labelled noise that the stage removed."""
        return _ratio(self.noise - self.kept_noise, self.noise, "noise")

    @property
    def false_prune_rate(self) -> float:
        """Share of the labelled evidence that the stage wrongly removed."""
        return _ratio(self.evidence - self.kept_evidence, self.evidence, "evidence")


def stage_counts(raw: int, kept: Iterable[AnomalySignal], evidence: Iterable[SignalKey]) -> StageCounts:
    """Count a stage's output against ground-truth evidence, matched by (service, signal name).

    `evidence` is a multiset: list a key twice if the input holds two evidence signals with it.
    """
    kept_keys = Counter((signal.service, signal.name) for signal in kept)
    evidence_keys = Counter(tuple(key) for key in evidence)
    return StageCounts(
        raw=raw,
        kept=sum(kept_keys.values()),
        evidence=sum(evidence_keys.values()),
        kept_evidence=sum((kept_keys & evidence_keys).values()),
    )


def _ratio(part: int, whole: int, name: str) -> float:
    if whole == 0:
        raise ValueError(f"undefined: {name} is 0")
    return part / whole
