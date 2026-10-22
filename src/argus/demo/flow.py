"""The incident run as a pipeline of stages, for the dashboard (app.py) and the command line.

    Telemetry -> M4 compress -> M1 context -> M2 diagnose -> Formal Verification -> M2 feedback -> M4 execute

Each stage calls the real module code and returns plain data, which the page draws as soon as the
stage finishes. PP1 has no cluster, so four things are not real, and the page says so:
the telemetry is synthetic (or uploaded), M2's reads are answered from canned kubectl output,
the safety layer reads saved kubectl output, and M4's executor is a stub that runs nothing.
"""

import json
import time
from collections.abc import Iterator
from pathlib import Path

from argus.config import Settings
from argus.context.ingest import IngestError, parse_records
from argus.context.report import report_data
from argus.context.service import build_report
from argus.contracts import DiagnosisResult, GateDecision, ProposedAction, SafetyVerdict, TelemetryBatch
from argus.diagnosis.core.config import DiagnosisConfig
from argus.diagnosis.ports.fakes import FakeReadExecutor
from argus.diagnosis.service import diagnose_report
from argus.orchestration.execution import handle_action
from argus.orchestration.report import compression_report
from argus.orchestration.service import compress
from argus.safety import extractor
from argus.safety.gate import check

FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures"

# Sample incidents: the telemetry, and the canned output of the reads M2 runs on it.
SCENARIOS = {
    "Cart can't reach its cache (CART_ADDR missing)": {
        "telemetry": FIXTURES / "m1" / "scenario_01" / "telemetry.json",
        "reads": FIXTURES / "m2" / "scenario_01" / "reads.json",
    },
    "Cart keeps crashing (out of memory)": {
        "telemetry": FIXTURES / "demo" / "scenario_02" / "telemetry.json",
        "reads": FIXTURES / "demo" / "scenario_02" / "reads.json",
    },
    "Hotel search fails (MongoDB disk full)": {
        "telemetry": FIXTURES / "demo" / "scenario_03" / "telemetry.json",
        "reads": FIXTURES / "demo" / "scenario_03" / "reads.json",
    },
}

# The safety layer's rules (invariants I1-I4 and the replica range) in plain words, for the page.
RULE_NAMES = {
    "min_replicas": "fewer replicas than the minimum",
    "min_available_during_restart": "too few pods during the restart",
    "protected_namespace": "touches a protected namespace",
    "pvc_in_use": "deletes a PVC a pod is using",
    "replicas_in_int32_range": "an invalid replica count",
}

# How M2 labels a fix it sends for checking only (the start of its rationale, see diagnosis/service.py).
FOR_HUMAN = "FOR A HUMAN"
TENTATIVE = "TENTATIVE"

# The safety layer's stage. Its real name: the Proactive Formal Verification Safety Layer.
VERIFY = "Formal Verification"

STAGES = [
    "Telemetry",
    "M4 · Compress",
    "M1 · Context",
    "M2 · Diagnose",
    VERIFY,
    "M2 · Feedback",
    "M4 · Execute",
]


def load_telemetry(text: str) -> TelemetryBatch:
    """Parse a telemetry batch (contract v1 JSON). A bad file raises ValueError."""
    return TelemetryBatch.model_validate_json(text)


def canned_reads() -> FakeReadExecutor:
    """All sample incidents' canned kubectl output as one fake cluster, so an uploaded variant of
    a sample can be diagnosed too. A read that isn't canned comes back "unavailable"."""
    outputs = {}
    for scenario in SCENARIOS.values():
        data = json.loads(scenario["reads"].read_text(encoding="utf-8"))
        outputs.update(data["reads"])
    return FakeReadExecutor(outputs)


def namespace_of(batch: TelemetryBatch) -> str:
    """The incident's namespace: the most common one in the telemetry's Kubernetes records.

    M2 needs it, and M1's context doesn't carry one yet (M2's open team question Q1).
    kube-system is left out: it holds the cluster's own services, not the application.
    """
    counts = {}
    for record in batch.records:
        namespace = record.get("namespace")
        if record.get("kind") == "k8s" and namespace and namespace != "kube-system":
            counts[namespace] = counts.get(namespace, 0) + 1
    best = "default"
    for namespace, count in counts.items():
        if count > counts.get(best, 0):
            best = namespace
    return best


def run_flow(batch: TelemetryBatch, settings: Settings) -> Iterator[dict]:
    """Run one incident through every module, yielding each stage (in STAGES order) when it ends."""
    namespace = namespace_of(batch)
    reads = canned_reads()
    # Tentative fixes on: M2 sends a fix to the safety layer even when the reads did not confirm the
    # cause, or the fix is a person's call, so every stage runs. Safe only because the executor is a stub.
    config = DiagnosisConfig(namespace=namespace, tentative_fixes=True)

    # Telemetry: what came in.
    started = time.perf_counter()
    kinds = {}
    for record in batch.records:
        kind = record.get("kind", "unknown")
        kinds[kind] = kinds.get(kind, 0) + 1
    details = {
        "source": batch.source,
        "alert_time": str(batch.alert_time),
        "namespace": namespace,
        "kinds": kinds,
    }
    yield _stage(
        "Telemetry", "passed", f"{len(batch.records)} records, namespace {namespace}", started, details
    )

    # M4: compress the telemetry for M1.
    started = time.perf_counter()
    compressed = compress(batch)
    saved = 100 * (1 - compressed.compressed_size / compressed.original_size)
    details = {
        **compression_report(batch, compressed),
        "original_bytes": compressed.original_size,
        "compressed_bytes": compressed.compressed_size,
        "saved_percent": saved,
        "tsv": compressed.content,
    }
    line = f"{compressed.original_size} → {compressed.compressed_size} bytes (−{saved:.0f}%)"
    yield _stage("M4 · Compress", "passed", line, started, details)

    # M1: filter the noise and find the failing path.
    started = time.perf_counter()
    report = build_report(compressed)
    compute_ms = (time.perf_counter() - started) * 1000
    context = report.context
    m1 = report_data(report)
    m1["compute_ms"] = compute_ms
    m1["nrr"] = noise_reduction(batch, m1)
    failing = ", ".join(context.failing_services) or "none"
    line = f"kept {m1['kept_count']} of {m1['stage1_count']} signals; failing: {failing}"
    yield _stage("M1 · Context", "passed", line, started, m1)

    # M2: rank hypotheses, test them with reads, propose a fix.
    started = time.perf_counter()
    m2 = diagnose_report(context, config=config, reads=reads)
    diagnosis = DiagnosisResult.model_validate(m2["diagnosis"])
    status, line = _diagnosis_line(m2, diagnosis)
    yield _stage("M2 · Diagnose", status, line, started, m2)

    # Formal Verification: every proposed write goes through M4's action handler, which asks the
    # safety layer first.
    started = time.perf_counter()
    checks = handle_all(diagnosis.actions, settings)
    status, line = _verify_line(checks)
    facts = cluster_facts(namespace, settings)
    yield _stage(VERIFY, status, line, started, {"checks": checks, "facts": facts})

    # M2 again, only if the safety layer blocked something: M2 gets the BLOCK verdicts and answers once.
    started = time.perf_counter()
    blocked = blocked_verdicts(checks)
    feedback_checks = []
    for_a_person = labelled_commands(diagnosis.actions)
    if not blocked:
        yield _stage("M2 · Feedback", "skipped", "nothing was blocked", started, None)
    else:
        m2_again = diagnose_report(context, blocked, config=config, reads=reads)
        revised = DiagnosisResult.model_validate(m2_again["diagnosis"])
        feedback_checks = handle_all(revised.actions, settings)
        for_a_person |= labelled_commands(revised.actions)
        status, line = _feedback_line(feedback_checks)
        details = {"diagnosis": m2_again["diagnosis"], "checks": feedback_checks}
        yield _stage("M2 · Feedback", status, line, started, details)

    # M4: what reaches the executor. It is a stub in PP1: nothing runs on any cluster.
    started = time.perf_counter()
    every_check = checks + feedback_checks
    approved = approved_writes(every_check)
    automatic = [row for row in approved if row["command"] not in for_a_person]
    if automatic:
        status, line = "passed", f"{len(automatic)} approved fix sent to the executor (stub)"
    elif approved:
        # M2 labelled it TENTATIVE or FOR A HUMAN: approved by the safety layer, but a person runs it.
        status, line = "attention", "approved fix awaits a person's decision (marked for review)"
    elif for_a_person:
        status, line = "attention", "no approved fix: recommended command goes to a person"
    else:
        status, line = "attention", "no approved fix: hand the incident to a human"
    yield _stage("M4 · Execute", status, line, started, {"actions": every_check})


def handle_all(actions: list[ProposedAction], settings: Settings) -> list[dict]:
    """M4's action handler on each action: reads run freely, writes need the safety layer's APPROVE.

    Each write's row also keeps the safety layer's step-by-step trace, so the page can show its steps.
    """
    traces = {}

    def gate(action: ProposedAction) -> SafetyVerdict:
        trace = []
        traces[action.command] = trace
        return check(action, settings=settings, trace=trace)

    rows = []
    for action in actions:
        result = handle_action(action, gate=gate)
        row = {"command": action.command, "is_write": action.is_write, "verdict": None, "execution": None}
        row["trace"] = traces.get(action.command)
        if result.verdict is not None:
            row["verdict"] = result.verdict.model_dump(mode="json")
        if result.execution is not None:
            row["execution"] = result.execution.model_dump(mode="json")
        rows.append(row)
    return rows


def noise_reduction(batch: TelemetryBatch, m1: dict) -> dict | None:
    """M1's NRR (1 - kept / raw) after each stage, or None if there's nothing to divide by.

    Raw is the metric, log and k8s records: spans are graph input, not candidate signals. Same
    denominator as the M1 experiments.
    """
    try:
        parsed = parse_records(batch.records)
    except IngestError:
        return None
    raw = len(parsed.metrics) + len(parsed.logs) + len(parsed.k8s)
    if raw == 0:
        return None
    return {"raw": raw, "stage1": 1 - m1["stage1_count"] / raw, "stage2": 1 - m1["kept_count"] / raw}


def blocked_verdicts(checks: list[dict]) -> list[SafetyVerdict]:
    """The safety layer's BLOCK verdicts, as M4 hands them back to M2."""
    blocked = []
    for row in checks:
        if row["verdict"] is not None and row["verdict"]["decision"] == GateDecision.BLOCK.value:
            blocked.append(SafetyVerdict.model_validate(row["verdict"]))
    return blocked


def labelled_commands(actions: list[ProposedAction]) -> set[str]:
    """The writes M2 sent for checking only (TENTATIVE or FOR A HUMAN): a person decides on these."""
    return {a.command for a in actions if a.is_write and a.rationale.startswith((FOR_HUMAN, TENTATIVE))}


def approved_writes(checks: list[dict]) -> list[dict]:
    """The writes the safety layer approved."""
    approved = []
    for row in checks:
        if row["verdict"] is not None and row["verdict"]["decision"] == GateDecision.APPROVE.value:
            approved.append(row)
    return approved


def cluster_facts(namespace: str, settings: Settings) -> list[dict] | None:
    """The deployments the safety layer's extractor sees in the namespace (saved kubectl output), or None."""
    if not settings.m3_kubectl_output:
        return None
    try:
        snapshot = extractor.extract(namespace, extractor.saved_output(Path(settings.m3_kubectl_output)))
    except Exception:
        return None  # no saved output for this namespace: the safety layer itself blocks, and says why
    return snapshot["deployments"]


def outcome(stages: list[dict]) -> dict:
    """How the incident ended, in one sentence: approved, blocked, or not confident enough."""
    by_name = {}
    for stage in stages:
        by_name[stage["name"]] = stage
    checks = by_name[VERIFY]["details"]["checks"]
    feedback = by_name["M2 · Feedback"]["details"]
    if feedback is not None:
        checks = checks + feedback["checks"]

    m2 = by_name["M2 · Diagnose"]["details"]
    # A fix M2 sent for checking only (a person's call, or unconfirmed): a person still decides,
    # so M2's report, with its recommendation, stays in the outcome whatever the safety layer said.
    for_checking = []
    proposed = m2["diagnosis"]["actions"] + (feedback["diagnosis"]["actions"] if feedback is not None else [])
    for action in proposed:
        if action["is_write"] and action["rationale"].startswith((FOR_HUMAN, TENTATIVE)):
            for_checking.append(action)
    still_human = f"\n\nA person still decides. Diagnosis report: {m2['report_text']}" if for_checking else ""
    approved = approved_writes(checks)
    if approved:
        return {
            "kind": "approved",
            "title": "Fix approved by the safety layer" + (", but a person decides" if for_checking else ""),
            "command": approved[0]["command"],
            "text": in_plain_words(approved[0]["verdict"]) + still_human,
        }
    blocked = blocked_verdicts(checks)
    if blocked:
        return {
            "kind": "blocked",
            "title": "The safety layer blocked the fix, so the incident goes to a human",
            "command": blocked[0].command,
            "text": in_plain_words(blocked[0].model_dump(mode="json")) + still_human,
        }
    if not m2["low_confidence"] and m2["hypotheses"]:
        return {
            "kind": "handoff",
            "title": "The cause was found; the incident goes to a human for a safe fix",
            "command": None,
            "text": m2["report_text"],
        }
    return {
        "kind": "unsure",
        "title": "The diagnosis is not confident enough to propose a fix; the incident goes to a human",
        "command": None,
        "text": by_name["M2 · Diagnose"]["headline"],
    }


def in_plain_words(verdict: dict) -> str:
    """A safety verdict as one sentence a non-expert can follow (the exact reason stays on the page)."""
    if verdict["decision"] == GateDecision.APPROVE.value:
        return "Z3 found no end state of this command that breaks one of the safety rules."
    example = verdict["counterexample"]
    if example is not None and "during" in example:
        before = example["before"]
        during = example["during"]
        return (
            f"During the restart {during['pods_down']} of {before['replicas']} pods would be down, "
            f"leaving {during['available']}; the minimum is {before['min_replicas']}."
        )
    if example is not None and "replicas" in example.get("after", {}):
        minimum = example["before"].get("min_replicas")
        return f"It would leave {example['after']['replicas']} replicas; the minimum is {minimum}."
    if verdict["violated_invariants"]:
        return "It breaks a rule: " + rule_names(verdict) + "."
    return verdict["reason"]


def rule_names(verdict: dict) -> str:
    """The rules a BLOCK verdict breaks, in plain words."""
    names = []
    for rule in verdict["violated_invariants"]:
        names.append(RULE_NAMES.get(rule, rule))
    return ", ".join(names)


def routing_record(stages: list[dict]) -> dict:
    """The run in the shape M4's offline routing replay reads (argus.orchestration.report)."""
    by_name = {}
    for stage in stages:
        by_name[stage["name"]] = stage
    diagnosis = by_name["M2 · Diagnose"]["details"]["diagnosis"]
    actions = by_name[VERIFY]["details"]["checks"]
    rounds = [{"title": "Diagnose Cause", "hypotheses": diagnosis["hypotheses"], "actions": actions}]
    return {"context": by_name["M1 · Context"]["details"]["context"], "rounds": rounds}


def _diagnosis_line(m2: dict, diagnosis: DiagnosisResult) -> tuple[str, str]:
    if not m2["hypotheses"]:
        return "attention", "no hypothesis: nothing to diagnose"
    top = m2["hypotheses"][0]
    line = f"{top['component']} [{top['layer']}] at {top['probability']:.0%}"
    for action in diagnosis.actions:
        if action.is_write and action.rationale.startswith(FOR_HUMAN):
            return "attention", line + "; confirmed, the fix is a person's call: sent for checking anyway"
        if action.is_write and action.rationale.startswith(TENTATIVE):
            return "attention", line + "; not confirmed: tentative fix sent for checking"
        if action.is_write:
            return "passed", line + "; proposes a fix"
    if not m2["low_confidence"]:
        return "attention", line + "; confirmed, no safe automatic fix: recommendation for a human"
    return "attention", line + "; not confirmed, no fix proposed"


def _verify_line(checks: list[dict]) -> tuple[str, str]:
    writes = [row for row in checks if row["is_write"]]
    if not writes:
        return "skipped", "no write to check"
    for row in writes:
        verdict = row["verdict"]
        if verdict["decision"] == GateDecision.BLOCK.value:
            if verdict["violated_invariants"]:
                return "blocked", "BLOCK: " + rule_names(verdict)
            return "blocked", "BLOCK: " + verdict["reason"]  # decided before the solver (fail-closed)
    return "passed", "APPROVE: no rule broken"


def _feedback_line(checks: list[dict]) -> tuple[str, str]:
    writes = [row for row in checks if row["is_write"]]
    if not writes:
        return "attention", "no other safe fix: hand to a human"
    for row in writes:
        if row["verdict"]["decision"] == GateDecision.BLOCK.value:
            return "blocked", "new fix also blocked"
    return "passed", "new fix approved"


def _stage(name: str, status: str, headline: str, started: float, details: dict | None) -> dict:
    """One finished stage. status: passed, blocked, attention (needs a human) or skipped."""
    return {
        "name": name,
        "status": status,
        "headline": headline,
        "ms": (time.perf_counter() - started) * 1000,
        "details": details,
    }
