"""M2 settings: loop budgets, mechanism flags and the ablation presets (A1-A5)."""

from dataclasses import dataclass, field, replace

from argus.diagnosis.belief import Params


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
    graph_priors: bool = True
    params: Params = field(default_factory=Params)


# Each preset only lists what differs from the full method.
PRESETS: dict[str, dict] = {
    "greedy": {"k": 1, "use_h0": False, "use_eig": False, "backtracking": False, "graph_priors": False},
    "A2": {"use_eig": False, "backtracking": False, "graph_priors": False},
    "A3": {"backtracking": False, "graph_priors": False},
    "A4": {"graph_priors": False},
    "ach_rca": {},  # A5: everything on
}


def preset(name: str, **overrides) -> DiagnosisConfig:
    """Build a config from a named preset, e.g. preset("greedy", namespace="social-network")."""
    return replace(DiagnosisConfig(), **{**PRESETS[name], **overrides})
