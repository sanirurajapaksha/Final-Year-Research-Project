"""Evaluate M3 on a labelled command corpus (for example data/corpora/m3_v0).

    python -m argus.safety.evaluate data/corpora/m3_v0 experiments/2026-10-13_m3_corpus-v0 --runs 5

Writes these files into OUT/results/ (raw evidence: never edit them by hand):
    verdicts.json      every check exactly as M3 returned it, one entry per command per run
    per_command.json   each command's label next to M3's decision and reason (run 1), and every
                       run's decision (an LLM answer can change between runs)
    metrics.json       rates with exact 95% confidence intervals, and latency per stage
    llm_outputs.jsonl  every raw answer of M3's LLM Formulation Agent (patch commands)

    detection   = unsafe commands blocked / unsafe commands
    false-block = safe commands blocked / safe commands

Gate (a), "no gate", approves every command, so its rates are known without running it:
detection 0 and false-block 0. Needs the 'eval' extra (SciPy).
"""

import argparse
import json
import math
import platform
import statistics
import subprocess
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv
from scipy.stats import beta

from argus.config import Settings, load_settings
from argus.contracts import GateDecision, ProposedAction
from argus.safety.gate import check

STAGES = ["prefilter", "parse", "formulation", "facts", "sandbox_total", "solver"]

# Verdict reasons that stop the run (see run_corpus).
MACHINE_FAILURES = ("solver:", "formulation: LLM:", "formulation: can't keep the raw LLM answer")


def clopper_pearson(k: int, n: int) -> tuple[float, float]:
    """Exact two-sided 95% confidence interval for k successes out of n trials (Clopper-Pearson)."""
    lower = 0.0
    if k > 0:
        lower = float(beta.ppf(0.025, k, n - k + 1))
    upper = 1.0
    if k < n:
        upper = float(beta.ppf(0.975, k + 1, n - k))
    return lower, upper


def rate(k: int, n: int) -> dict:
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    lower, upper = clopper_pearson(k, n)
    return {"k": k, "n": n, "rate": k / n, "ci95": [lower, upper]}


def rates_for(rows: list[dict]) -> dict:
    """Detection and false-block rates for rows that each have a 'label' and a 'blocked' flag."""
    unsafe = 0
    unsafe_blocked = 0
    safe = 0
    safe_blocked = 0
    for row in rows:
        if row["label"] == "unsafe":
            unsafe += 1
            if row["blocked"]:
                unsafe_blocked += 1
        else:
            safe += 1
            if row["blocked"]:
                safe_blocked += 1
    return {"detection": rate(unsafe_blocked, unsafe), "false_block": rate(safe_blocked, safe)}


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile: the smallest value with at least p% of the values at or below it."""
    ordered = sorted(values)
    rank = math.ceil(p / 100 * len(ordered))
    return ordered[max(rank, 1) - 1]


def latency(verdicts: list[dict]) -> dict:
    """Median and p95 per stage, in ms, over the checks that reached that stage."""
    summary = {}
    for stage in STAGES:
        values = []
        for verdict in verdicts:
            if stage in verdict["timings_ms"]:
                values.append(verdict["timings_ms"][stage])
        if values:
            summary[stage] = {
                "n": len(values),
                "median": statistics.median(values),
                "p95": percentile(values, 95),
            }
    return summary


def run_corpus(corpus_dir: Path, runs: int, settings: Settings) -> tuple[list[dict], list[dict]]:
    """Check every command `runs` times. Returns (one row per command, every verdict)."""
    commands = json.loads((corpus_dir / "commands.json").read_text(encoding="utf-8"))
    rows = []
    verdicts = []
    for item in commands:
        snapshot = json.loads((corpus_dir / item["snapshot"]).read_text(encoding="utf-8"))
        decisions = []
        reasons = []
        used_llm = False
        for run_number in range(1, runs + 1):
            verdict = check(ProposedAction(command=item["command"], is_write=True), snapshot, settings)
            # A sandbox or solver failure (crash, timeout, memory), an LLM outage (no key, network,
            # timeout) or a raw LLM answer that can't be logged says something about the machine,
            # not about M3's rules, so stop instead of counting it as a block. An LLM answer that
            # disagrees with the command still counts.
            if verdict.reason.startswith(MACHINE_FAILURES):
                raise RuntimeError(f"{item['id']}: {verdict.reason}; no results written")
            record = verdict.model_dump(mode="json")
            record["id"] = item["id"]
            record["run"] = run_number
            verdicts.append(record)
            decisions.append(verdict.decision)
            reasons.append(verdict.reason)
            if "formulation" in verdict.timings_ms:
                used_llm = True
        # Without the LLM, M3 is deterministic, so every run must give the same decision.
        # With the LLM (patch commands) the answer can change between runs (decided 19/10):
        # every run is kept, and the command is marked as flipped.
        flipped = False
        for decision in decisions:
            if decision is not decisions[0]:
                flipped = True
        if flipped and not used_llm:
            raise RuntimeError(f"{item['id']}: the decision changed between runs: {decisions}")
        run_decisions = []
        for decision in decisions:
            run_decisions.append(decision.value)
        rows.append(
            {
                "id": item["id"],
                "group": item["group"],
                "verb": item["verb"],
                "label": item["label"],
                "category": item["category"],
                "review": item["review"],
                "decision": decisions[0].value,
                "blocked": decisions[0] is GateDecision.BLOCK,
                "reason": reasons[0],
                "decisions": run_decisions,
                "reasons": reasons,
                "flipped": flipped,
            }
        )
    return rows, verdicts


def metrics(rows: list[dict], verdicts: list[dict]) -> dict:
    by_verb = {}
    for verb in sorted({row["verb"] for row in rows}):
        by_verb[verb] = rates_for([row for row in rows if row["verb"] == verb])

    by_group = {}
    for group in sorted({row["group"] for row in rows}):
        by_group[group] = rates_for([row for row in rows if row["group"] == group])

    # Detection per unsafe category (1-4 in LABELLING.md); safe commands have no category.
    by_category = {}
    for category in (1, 2, 3, 4):
        unsafe_rows = [row for row in rows if row["category"] == category]
        by_category[str(category)] = rates_for(unsafe_rows)["detection"]

    # Gate (a) approves everything.
    no_gate = []
    for row in rows:
        no_gate.append({"label": row["label"], "blocked": False})

    # Patch commands go through the LLM Formulation Agent: did they reach M3's rules?
    patches = 0
    checked_by_rules = 0
    for row in rows:
        if row["verb"] == "patch":
            patches += 1
            if not row["reason"].startswith("formulation:"):
                checked_by_rules += 1

    # Every run counted on its own (the LLM can answer differently each run), and the commands
    # whose decision changed between runs.
    every_run = []
    flipped_ids = []
    for row in rows:
        for decision in row["decisions"]:
            every_run.append({"label": row["label"], "blocked": decision == GateDecision.BLOCK.value})
        if row["flipped"]:
            flipped_ids.append(row["id"])

    return {
        "gate_c_m3": {
            "overall": rates_for(rows),
            "overall_every_run": rates_for(every_run),
            "by_verb": by_verb,
            "by_group": by_group,
            "by_category": by_category,
        },
        "gate_a_no_gate": {"overall": rates_for(no_gate)},
        "formulation": {
            "patch_commands": patches,
            "checked_by_rules": checked_by_rules,
            "blocked_by_formulation": patches - checked_by_rules,
            "decision_changed_between_runs": flipped_ids,
        },
        "latency_ms": latency(verdicts),
    }


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(
        prog="python -m argus.safety.evaluate", description="Evaluate M3 on a corpus."
    )
    cli.add_argument("corpus", type=Path, help="corpus folder with commands.json")
    cli.add_argument("out", type=Path, help="experiment folder; results go to OUT/results/")
    cli.add_argument("--runs", type=int, default=5, help="checks per command (for latency); default 5")
    args = cli.parse_args(argv)

    # Read the code version before the run: the run itself writes the LLM log into OUT/results/,
    # which would otherwise show up as an uncommitted change.
    commit = _git("rev-parse", "HEAD")
    uncommitted_changes = _git("status", "--porcelain") != ""

    # Every raw LLM answer is kept with the results, as evidence.
    settings = replace(load_settings(), m3_llm_log=str(args.out / "results" / "llm_outputs.jsonl"))
    rows, verdicts = run_corpus(args.corpus, args.runs, settings)

    # Results count only once every label has been reviewed (LABELLING.md).
    labels = "reviewed"
    for row in rows:
        if row["review"] != "reviewed":
            labels = "PRELIMINARY: draft labels, not for reporting"

    summary = {
        "corpus": str(args.corpus),
        "commands": len(rows),
        "runs_per_command": args.runs,
        "labels": labels,
        "commit": commit,
        "uncommitted_changes": uncommitted_changes,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "solver_timeout_s": settings.solver_timeout_s,
        "solver_memory_mb": settings.solver_memory_mb,
        "llm_model": settings.llm_model,
    }
    summary.update(metrics(rows, verdicts))

    results = args.out / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "verdicts.json").write_text(json.dumps(verdicts, indent=1), encoding="utf-8")
    (results / "per_command.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (results / "metrics.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    detection = summary["gate_c_m3"]["overall"]["detection"]
    false_block = summary["gate_c_m3"]["overall"]["false_block"]
    print(f"labels: {summary['labels']}")
    print(f"detection   {detection['k']}/{detection['n']}  CI95 {detection['ci95']}")
    print(f"false-block {false_block['k']}/{false_block['n']}  CI95 {false_block['ci95']}")
    print(f"results written to {results}")
    return 0


if __name__ == "__main__":
    # Settings and the LLM key from .env in the current folder; variables already set win.
    load_dotenv(".env")
    raise SystemExit(main())
