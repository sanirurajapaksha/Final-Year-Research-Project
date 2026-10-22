"""Belief tracker: probabilities over rival root-cause hypotheses (pure Python, no I/O)."""

from dataclasses import dataclass, field

H0 = "H0"  # "none of the listed hypotheses": keeps the world open

# How much one verdict multiplies a hypothesis's belief.
LAMBDA = {
    "strong-support": 4.0,
    "weak-support": 1.5,
    "neutral": 1.0,
    "weak-refute": 0.5,
    "strong-refute": 0.1,
}


@dataclass
class Params:
    pi0: float = 0.15  # starting belief of H0
    theta: float = 0.80  # stop when the top belief reaches this...
    delta: float = 0.30  # ...and leads the runner-up by this much
    eps: float = 0.05  # prune hypotheses below this
    rho: float = 0.30  # if the best real belief is below this, think again
    inherit: float = 0.8  # share of H0's mass given to new hypotheses


@dataclass
class BeliefState:
    params: Params = field(default_factory=Params)
    belief: dict[str, float] = field(default_factory=dict)  # hypothesis id -> probability
    status: dict[str, str] = field(default_factory=dict)  # "active" or "pruned"
    history: list[dict] = field(default_factory=list)  # every change, for the trajectory log

    def init(self, scores: dict[str, float]) -> None:
        """Starting beliefs: H0 gets pi0, the rest is shared in proportion to each score."""
        if not scores or min(scores.values()) <= 0:
            raise ValueError("need a positive score for at least one hypothesis")
        total = sum(scores.values())
        rest = 1.0 - self.params.pi0
        self.belief = {h: rest * s / total for h, s in scores.items()}
        self.belief[H0] = self.params.pi0
        self.status = {h: "active" for h in self.belief}
        self._log("init")

    def active(self) -> list[str]:
        """Real hypotheses still in play (never H0)."""
        return [h for h, s in self.status.items() if s == "active" and h != H0]

    def update(self, verdicts: dict[str, str], evidence_id: str) -> None:
        """Apply one test result. Missing or unknown ids count as neutral."""
        for h in self.active():
            self.belief[h] *= LAMBDA[verdicts.get(h, "neutral")]
        self._normalize()
        self._prune()
        self._log("update", evidence=evidence_id, verdicts=dict(verdicts))

    def decide(self) -> str:
        """'stop', 'continue' or 'rehypothesize'."""
        real = sorted((b for h, b in self.belief.items() if h != H0), reverse=True)
        top = real[0] if real else 0.0
        runner_up = max(real[1] if len(real) > 1 else 0.0, self.belief.get(H0, 0.0))
        if top >= self.params.theta and top - runner_up >= self.params.delta:
            return "stop"
        if not self.active() or self.belief.get(H0, 0.0) >= top or top < self.params.rho:
            return "rehypothesize"
        return "continue"

    def ranked(self) -> list[tuple[str, float]]:
        """All hypotheses, highest belief first."""
        return sorted(self.belief.items(), key=lambda kv: -kv[1])

    def add_hypotheses(self, new_ids: list[str], scores: dict[str, float] | None = None) -> None:
        """New hypotheses inherit part of H0's mass (used after rehypothesize).

        The inherited mass is shared in proportion to `scores` (the same c x g as in init), so the
        graph prior still counts after backtracking; without scores it is shared equally.
        """
        for h in new_ids:
            if h in self.belief:
                raise ValueError(f"duplicate hypothesis id {h}")
        weight = {h: (scores or {}).get(h, 1.0) for h in new_ids}
        if min(weight.values(), default=1.0) <= 0:
            raise ValueError("need a positive score for every new hypothesis")
        total = sum(weight.values())
        share = self.params.inherit * self.belief[H0]
        for h in new_ids:
            self.belief[h] = share * weight[h] / total
            self.status[h] = "active"
        self.belief[H0] -= share
        self._log("rehypothesize", added=list(new_ids))

    def _normalize(self) -> None:
        total = sum(self.belief.values())
        for h in self.belief:
            self.belief[h] /= total

    def _prune(self) -> None:
        for h, b in self.belief.items():
            if h == H0:
                continue
            self.status[h] = "pruned" if b < self.params.eps else "active"

    def _log(self, event: str, **data) -> None:
        self.history.append(
            {"event": event, "belief": dict(self.belief), "status": dict(self.status), **data}
        )
