"""Record offline router latency and plans, never provider cost or API usage.

python -m argus.orchestration.router_benchmark REQUEST --output-dir FRESH_DIR
"""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

import z3
from pydantic import ValidationError

from argus.orchestration import router
from argus.orchestration.router import RoutingRequest, route


def _nonnegative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def _positive(value: str) -> int:
    number = _nonnegative(value)
    if number == 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--budgets", type=_nonnegative, nargs="+")
    parser.add_argument("--repetitions", type=_positive, default=10)
    parser.add_argument("--warmups", type=_nonnegative, default=1)
    parser.add_argument("--solver-timeout-ms", type=_positive, default=5000)
    args = parser.parse_args(argv)

    try:
        if args.output_dir.exists():
            raise ValueError("output directory already exists; use a fresh directory to preserve evidence")
        input_bytes = args.request.read_bytes()
        request = RoutingRequest.model_validate_json(input_bytes)
        budgets = args.budgets if args.budgets is not None else [request.remaining_budget_units]
        if len(set(budgets)) != len(budgets):
            raise ValueError("budget cases must be unique")

        root = Path(__file__).resolve().parents[3]
        source_paths = [Path(router.__file__), Path(__file__), root / "pyproject.toml"]
        sources = {str(path.relative_to(root)): path.read_bytes() for path in source_paths}
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10
        ).strip()
        dirty_paths = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            text=True,
            timeout=10,
        ).splitlines()
        config = {
            "measurement": "offline routing latency; no model calls, token counts or billed costs",
            "command": [sys.executable, "-m", __spec__.name, *(sys.argv[1:] if argv is None else argv)],
            "source_commit": commit,
            "source_dirty": bool(dirty_paths),
            "dirty_paths": dirty_paths,
            "source_snapshot_sha256": {
                name: hashlib.sha256(data).hexdigest() for name, data in sources.items()
            },
            "input_path": str(args.request.resolve()),
            "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "packages": {name: importlib.metadata.version(name) for name in ("pydantic", "z3-solver")},
            "z3_version": z3.get_version_string(),
            "budgets": budgets,
            "repetitions_per_case": args.repetitions,
            "warmups_per_case": args.warmups,
            "solver_timeout_ms": args.solver_timeout_ms,
            "timing_scope": (
                "route() call including validation, context creation, encoding and solve; excludes imports"
            ),
            "cost_unit": request.cost_unit,
            "quality_source": request.quality_source,
            "objective": request.objective,
        }

        rows = []
        summaries = []
        plans = {}
        for case_index, budget in enumerate(budgets):
            case = RoutingRequest.model_validate({**request.model_dump(), "remaining_budget_units": budget})
            reference = None
            phases = [("process_first_call" if case_index == 0 else "case_first_call", 0)]
            phases.extend(("warmup", i) for i in range(args.warmups))
            phases.extend(("measured", i) for i in range(args.repetitions))
            for phase, repetition in phases:
                started = perf_counter_ns()
                plan = route(case, timeout_ms=args.solver_timeout_ms)
                elapsed_ms = (perf_counter_ns() - started) / 1_000_000
                data = plan.model_dump(mode="json")
                if reference is None:
                    reference = data
                elif data != reference:
                    raise ValueError(f"non-repeatable plan for budget {budget}; no measurement saved")
                rows.append(
                    {
                        "budget_units": budget,
                        "phase": phase,
                        "repetition": repetition,
                        "elapsed_ms": elapsed_ms,
                        "status": plan.status,
                        "estimated_cost_units": plan.total_estimated_cost_units,
                        "estimated_quality": plan.total_estimated_quality,
                    }
                )
            times = [
                row["elapsed_ms"]
                for row in rows
                if row["budget_units"] == budget and row["phase"] == "measured"
            ]
            plans[f"budget-{budget}"] = reference
            summaries.append(
                {
                    "budget_units": budget,
                    "task_count": len(case.tasks),
                    "candidate_count": len(case.candidates),
                    "status": reference["status"],
                    "measured_repetitions": len(times),
                    "median_ms": statistics.median(times),
                    "min_ms": min(times),
                    "max_ms": max(times),
                }
            )

        # Exclusive directory creation also protects against concurrent writers.
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "request.json").write_bytes(input_bytes)
        for name, data in sources.items():
            target = args.output_dir / "source_snapshot" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for name, data in (("config", config), ("plans", plans), ("summary", summaries)):
            (args.output_dir / f"{name}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        with (args.output_dir / "timings.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps(summaries, indent=2))
        return 1 if any(summary["status"] == "solver_error" for summary in summaries) else 0
    except (OSError, ValueError, ValidationError, subprocess.SubprocessError) as error:
        print(f"router benchmark: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
