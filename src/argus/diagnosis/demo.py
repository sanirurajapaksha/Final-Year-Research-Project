"""M2 for the PP1 demo: the REAL diagnose() with FAKE reads (canned scenario_01 kubectl output).

There is no cluster for PP1, so every read M2 runs is answered from
data/fixtures/m2/scenario_01/reads.json, which is hand-written. A read that isn't in the
file comes back "unavailable", exactly as with no cluster. Nothing here touches a cluster.
"""

import json
from pathlib import Path

from argus.contracts import DiagnosisResult, GateDecision, SafetyVerdict, SemanticContext
from argus.diagnosis.ports.fakes import FakeReadExecutor
from argus.diagnosis.service import diagnose, diagnose_report

REPO = Path(__file__).resolve().parents[3]
SCENARIO_READS = REPO / "data" / "fixtures" / "m2" / "scenario_01" / "reads.json"
FAKE_READS_LABEL = "FAKE reads: canned scenario_01 kubectl output, no cluster"
SIMULATED_BLOCK_REASON = "SIMULATED BLOCK: hand-made on the M2 page, not a real M3 verdict"


def scenario_reads(path: Path = SCENARIO_READS) -> FakeReadExecutor:
    """A read executor that answers from the canned file instead of a cluster."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FakeReadExecutor(data["reads"])


def demo_diagnose(context: SemanticContext, feedback: list[SafetyVerdict] | None = None) -> DiagnosisResult:
    """Called like diagnose(), so the demo can pass it to run_once(..., diagnoser=demo_diagnose)."""
    return diagnose(context, feedback, reads=scenario_reads())


def demo_report(context: SemanticContext, feedback: list[SafetyVerdict] | None = None) -> dict:
    """diagnose_report() with the canned reads, labelled as fake, for the M2 dashboard page."""
    report = diagnose_report(context, feedback, reads=scenario_reads())
    report["reads_source"] = FAKE_READS_LABEL
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
