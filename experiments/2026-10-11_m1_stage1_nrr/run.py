"""W2-06: first noise-reduction ratio for M1 Stage 1 on scenario_01.

Run from the repository root:  python experiments/2026-10-11_m1_stage1_nrr/run.py
Writes results/ next to this file. Don't overwrite an earlier run: copy this script to a new
dated folder instead.
"""

import json
import platform
import statistics
import subprocess
import sys
from pathlib import Path

from argus.common.timing import stage_timer
from argus.context.filters import Thresholds, extract_anomalies
from argus.context.ingest import decode_tsv, parse_records
from argus.context.metrics import stage_counts
from argus.context.service import build_context
from argus.contracts import TelemetryBatch
from argus.orchestration.service import compress

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCENARIO = ROOT / "data" / "fixtures" / "m1" / "scenario_01"
REPEATS = 200


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    batch = TelemetryBatch.model_validate_json((SCENARIO / "telemetry.json").read_text(encoding="utf-8"))
    truth = json.loads((SCENARIO / "ground_truth.json").read_text(encoding="utf-8"))
    evidence = truth["stage1_expected"]["relevant"]
    thresholds = Thresholds()

    # Stage 1 reads metrics, logs and k8s records; spans are F2 input.
    telemetry = parse_records(batch.records)
    stage1_input = len(telemetry.metrics) + len(telemetry.logs) + len(telemetry.k8s)
    direct = extract_anomalies(telemetry, thresholds)
    counts = stage_counts(stage1_input, direct, evidence)

    # The same data through M4's real compress() and M1's public entry point.
    compressed = compress(batch)
    context = build_context(compressed, thresholds)
    same_via_m4 = context.kept_signals == direct

    # Compute time only (no fetching: the input is already in memory), median over REPEATS.
    runs: dict[str, list[float]] = {"decode": [], "parse": [], "filter": [], "total": []}
    for _ in range(REPEATS):
        timings: dict[str, float] = {}
        with stage_timer(timings, "total"):
            with stage_timer(timings, "decode"):
                records = decode_tsv(compressed.content)
            with stage_timer(timings, "parse"):
                parsed = parse_records(records)
            with stage_timer(timings, "filter"):
                extract_anomalies(parsed, thresholds)
        for stage, value in timings.items():
            runs[stage].append(value)

    summary = {
        "scenario": truth["scenario"],
        "provenance": truth["provenance"],
        "n_scenarios": 1,
        "records_total": len(batch.records),
        "stage1_input_signals": counts.raw,
        "stage1_kept_signals": counts.kept,
        "labelled_evidence": counts.evidence,
        "labelled_noise": counts.noise,
        "kept_evidence": counts.kept_evidence,
        "kept_noise": counts.kept_noise,
        "nrr": counts.nrr,
        "labelled_nrr": counts.labelled_nrr,
        "false_prune_rate": counts.false_prune_rate,
        "same_result_via_m4_compress_and_build_context": same_via_m4,
        "compute_time_ms_median": {stage: statistics.median(values) for stage, values in runs.items()},
        "timing_repeats": REPEATS,
        "thresholds": {
            "metrics": thresholds.metrics,
            "log_severities": sorted(thresholds.log_severities),
            "max_restarts": thresholds.max_restarts,
            "crash_statuses": sorted(thresholds.crash_statuses),
        },
    }
    config = {
        "command": "python experiments/2026-10-11_m1_stage1_nrr/run.py",
        "commit": git("rev-parse", "HEAD"),
        "uncommitted_changes_outside_this_folder": bool(
            git("status", "--porcelain", "--", ".", ":(exclude)experiments/2026-10-11_m1_stage1_nrr")
        ),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "input": "data/fixtures/m1/scenario_01/telemetry.json",
        "model": "None; M1 makes no model calls.",
    }

    results = HERE / "results"
    results.mkdir(exist_ok=True)
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (results / "anomalies.json").write_text(
        json.dumps([signal.model_dump(mode="json") for signal in direct], indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
