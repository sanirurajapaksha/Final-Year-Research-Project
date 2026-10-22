"""M2 settings: loop budgets, mechanism flags and the ablation presets (A1-A5)."""

from dataclasses import dataclass, field, replace
from typing import Literal

from argus.diagnosis.core.belief import Params

# How the graph prior g(component) is set:
#   off     - not used: every component counts 1.0 in the prior (candidate order is still by weight)
#   almanac - the Almanac's three levels: deepest failing 1.5, rest of the failing path 1.0, others 0.5
#   hop     - graded by hops from the deepest failing service, plus quiet dependencies (context_adapter)
GraphPriors = Literal["off", "almanac", "hop"]


@dataclass(frozen=True)
class DiagnosisConfig:
    namespace: str = "default"  # not in SemanticContext yet (team question Q1)
    # Hypotheses and loop budgets
    k: int = 3  # hypotheses per round
    max_rounds: int = 4
    max_reads: int = 25
    max_rehyp: int = 2
    max_revisions: int = 2  # M3 BLOCKs before giving up on a write
    wall_clock_s: float = 900.0
    max_output_chars: int = 6000  # tool output kept per read
    # Mechanism flags: each one is an ablation switch
    use_h0: bool = True
    use_eig: bool = True
    backtracking: bool = True
    graph_priors: GraphPriors = "almanac"
    # At most this many hypotheses per component in a round (None: no limit). Spreading tests rival
    # services earlier, but costs a read when the origin really is the cause; Step 10 measures it.
    per_component: int | None = None
    # Who drafts hypotheses: "llm" uses the LLM when one is configured and falls back to the rules
    # (so with no key it behaves exactly like "rules"); "rules" never asks the LLM, for the R-* baselines.
    generator: Literal["llm", "rules"] = "llm"
    params: Params = field(default_factory=Params)

    def __post_init__(self) -> None:
        # Older callers pass True/False: True meant the Almanac's prior, False meant none.
        if self.graph_priors is True:
            object.__setattr__(self, "graph_priors", "almanac")
        elif self.graph_priors is False:
            object.__setattr__(self, "graph_priors", "off")
        if self.generator not in ("llm", "rules"):
            raise ValueError(f"generator must be llm or rules, not {self.generator!r}")
        if self.graph_priors not in ("off", "almanac", "hop"):
            raise ValueError(f"graph_priors must be off, almanac or hop, not {self.graph_priors!r}")


# Each preset only lists what differs from the full method.
PRESETS: dict[str, dict] = {
    "greedy": {"k": 1, "use_h0": False, "use_eig": False, "backtracking": False, "graph_priors": "off"},
    "A2": {"use_eig": False, "backtracking": False, "graph_priors": "off"},
    "A3": {"backtracking": False, "graph_priors": "off"},
    "A4": {"graph_priors": "off"},
    "ach_rca": {},  # A5: everything on, with the Almanac's graph prior
    "A5-hop": {"graph_priors": "hop"},  # A5 with the hop-graded graph prior
}


def preset(name: str, **overrides) -> DiagnosisConfig:
    """Build a config from a named preset, e.g. preset("greedy", namespace="social-network")."""
    return replace(DiagnosisConfig(), **{**PRESETS[name], **overrides})
