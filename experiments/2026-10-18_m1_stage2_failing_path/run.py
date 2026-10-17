"""W3-04: Stage 2 (failing-path pruning) against Stage 1 alone on scenario_01.

Run from the repository root:  python experiments/2026-10-18_m1_stage2_failing_path/run.py
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
from argus.context.isolator import prune
from argus.context.metrics import stage_counts
from argus.context.sdg import DEFAULT_LOOKBACK, build_graph, spans_in_window
from argus.context.service import STRATEGIES, build_report
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
    fault_service = truth["fault"]["service"]
    thresholds = Thresholds()
    compressed = compress(batch)

    # Both strategies through M4's real compress() and M1's public entry point. Ratios use the same
    # denominator: the metric, log and k8s records (spans are graph input, not candidate signals).
    parsed = parse_records(batch.records)
    raw = len(parsed.metrics) + len(parsed.logs) + len(parsed.k8s)
    strategies = {}
    reports = {}
    for strategy in STRATEGIES:
        report = build_report(compressed, thresholds, strategy)
        counts = stage_counts(raw, report.context.kept_signals, evidence)
        reports[strategy] = report
        strategies[strategy] = {
            "kept_signals": counts.kept,
            "kept_evidence": counts.kept_evidence,
            "kept_noise": counts.kept_noise,
            "nrr": counts.nrr,
            "labelled_nrr": counts.labelled_nrr,
            "false_prune_rate": counts.false_prune_rate,
            "fault_service_in_context": fault_service in report.context.services,
            "context_services": report.context.services,
        }

    # Compute time only (the input is already in memory), median over REPEATS.
    runs: dict[str, list[float]] = {
        stage: [] for stage in ("decode", "parse", "filter", "window", "graph", "prune", "total")
    }
    for _ in range(REPEATS):
        timings: dict[str, float] = {}
        with stage_timer(timings, "total"):
            with stage_timer(timings, "decode"):
                records = decode_tsv(compressed.content)
            with stage_timer(timings, "parse"):
                typed = parse_records(records)
            with stage_timer(timings, "filter"):
                signals = extract_anomalies(typed, thresholds)
            with stage_timer(timings, "window"):
                spans = spans_in_window(typed.spans, compressed.alert_time, DEFAULT_LOOKBACK)
            with stage_timer(timings, "graph"):
                graph = build_graph(spans)
            with stage_timer(timings, "prune"):
                prune(signals, graph)
        for stage, value in timings.items():
            runs[stage].append(value)

    failing = reports["failing_path"]
    summary = {
        "scenario": truth["scenario"],
        "provenance": truth["provenance"],
        "n_scenarios": 1,
        "records_total": len(batch.records),
        "spans": len(parsed.spans),
        "stage1_input_signals": raw,
        "labelled_evidence": len(evidence),
        "labelled_noise": raw - len(evidence),
        "fault_service": fault_service,
        "strategies": strategies,
        "failing_path": {
            "failing_services": failing.context.failing_services,
            "entry_point": failing.context.entry_point,
            "dependencies": failing.context.dependencies,
            "pruned": [
                {"service": item.signal.service, "name": item.signal.name, "reason": item.reason}
                for item in failing.pruned
            ],
        },
        "compute_time_ms_median": {stage: statistics.median(values) for stage, values in runs.items()},
        "timing_repeats": REPEATS,
        "lookback_seconds": DEFAULT_LOOKBACK.total_seconds(),
    }
    config = {
        "command": "python experiments/2026-10-18_m1_stage2_failing_path/run.py",
        "commit": git("rev-parse", "HEAD"),
        "uncommitted_changes_outside_this_folder": bool(
            git("status", "--porcelain", "--", ".", ":(exclude)experiments/2026-10-18_m1_stage2_failing_path")
        ),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "input": "data/fixtures/m1/scenario_01/telemetry.json",
        "model": "None; M1 makes no model calls.",
    }

    results = HERE / "results"
    results.mkdir(exist_ok=True)
    (results / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (results / "context_failing_path.json").write_text(
        failing.context.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
