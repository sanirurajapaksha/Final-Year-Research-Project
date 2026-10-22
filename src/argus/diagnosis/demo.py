"""M2 for the PP1 demo: the REAL diagnose() with FAKE reads (canned scenario_01 kubectl output).

There is no cluster for PP1, so every read M2 runs is answered from
data/fixtures/m2/scenario_01/reads.json, which is hand-written. A read that isn't in the
file comes back "unavailable", exactly as with no cluster. Nothing here touches a cluster.
"""

import json
from pathlib import Path

from argus.config import load_settings
from argus.contracts import DiagnosisResult, GateDecision, SafetyVerdict, SemanticContext
from argus.diagnosis.ports.fakes import FakeReadExecutor, NoLLM
from argus.diagnosis.ports.openrouter import llm_from_env
from argus.diagnosis.service import diagnose, diagnose_report

REPO = Path(__file__).resolve().parents[3]
SCENARIO_READS = REPO / "data" / "fixtures" / "m2" / "scenario_01" / "reads.json"
FAKE_READS_LABEL = "FAKE reads: canned scenario_01 kubectl output, no cluster"
NO_READS_LABEL = "NO reads: no cluster and no canned output, so every read comes back unavailable"
SIMULATED_BLOCK_REASON = "SIMULATED BLOCK: hand-made on the M2 page, not a real M3 verdict"


def scenario_reads(path: Path = SCENARIO_READS) -> FakeReadExecutor:
    """A read executor that answers from the canned file instead of a cluster."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FakeReadExecutor(data["reads"])


def _demo_llm(use_llm: bool):
    """The demo runs on rules unless asked: free, the same every time, and what main always did.
    use_llm=True (the page's toggle) is an explicit opt-in, so it builds the team's model from
    ARGUS_LLM_API_KEY / ARGUS_LLM_MODEL without needing ARGUS_M2_USE_LLM; with no key, rules."""
    if not use_llm:
        return NoLLM()
    return llm_from_env(load_settings().llm_model) or NoLLM()


def demo_diagnose(
    context: SemanticContext, feedback: list[SafetyVerdict] | None = None, use_llm: bool = False
) -> DiagnosisResult:
    """Called like diagnose(), so the demo can pass it to run_once(..., diagnoser=demo_diagnose)."""
    return diagnose(context, feedback, llm=_demo_llm(use_llm), reads=scenario_reads())


def demo_report(
    context: SemanticContext, feedback: list[SafetyVerdict] | None = None, use_llm: bool = False
) -> dict:
    """diagnose_report() with the canned reads, labelled as fake, for the M2 dashboard page."""
    report = diagnose_report(context, feedback, llm=_demo_llm(use_llm), reads=scenario_reads())
    report["reads_source"] = FAKE_READS_LABEL
    return report


def no_cluster_report(
    context: SemanticContext, feedback: list[SafetyVerdict] | None = None, use_llm: bool = False
) -> dict:
    """diagnose_report() with no reads at all: every read is unavailable, as with no cluster and no fakes."""
    report = diagnose_report(context, feedback, llm=_demo_llm(use_llm))
    report["reads_source"] = NO_READS_LABEL
    return report


def run_blocks(rounds: list[dict]) -> list[SafetyVerdict]:
    """M3's BLOCK verdicts from the first round of a demo run, as M4 hands them back to M2."""
    blocks: list[SafetyVerdict] = []
    if not rounds:
        return blocks
    for action in rounds[0]["actions"]:
        verdict = action["verdict"]
        if verdict is not None and verdict["decision"] == "BLOCK":
            blocks.append(SafetyVerdict.model_validate(verdict))
    return blocks


def simulated_block(command: str) -> SafetyVerdict:
    """A hand-made BLOCK of `command`, so the page can show M2's feedback path when M3 blocked nothing."""
    return SafetyVerdict(command=command, decision=GateDecision.BLOCK, reason=SIMULATED_BLOCK_REASON)


def prior_beliefs(report: dict) -> dict[str, float]:
    """Each hypothesis's belief when it first appears: at the start, or after a new round."""
    priors: dict[str, float] = {}
    for one_round in report["belief_rounds"]:
        for hypothesis_id, probability in one_round["belief"].items():
            if hypothesis_id not in priors:
                priors[hypothesis_id] = probability
    return priors


def read_verdicts(report: dict) -> dict[str, dict[str, str]]:
    """For each read (E id), the verdicts the scorer gave on it, e.g. {"E1": {"H1": "strong-support"}}."""
    verdicts: dict[str, dict[str, str]] = {}
    for one_round in report["belief_rounds"]:
        if one_round["evidence"]:
            verdicts[one_round["evidence"]] = one_round["verdicts"]
    return verdicts
