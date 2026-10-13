"""W2-08: byte-only M4 evaluation on the existing synthetic contract v1 scenario.

Run from the repository root with its virtual environment Python.
Use --output-dir for a fresh reproduction; saved evidence is never overwritten.
"""

import argparse
import csv
import hashlib
import io
import json
import platform
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from argus.context.ingest import decode_tsv, parse_records
from argus.contracts import TelemetryBatch
from argus.orchestration.service import compress

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INPUT = Path("data/fixtures/m1/scenario_01/telemetry.json")
TRUTH = INPUT.with_name("ground_truth.json")
BASELINE_RULE = (
    "json.dumps(batch.records, ensure_ascii=False); all other options use Python defaults: "
    "sort_keys=False, indent=None, separators=(', ', ': '), allow_nan=True. "
    "Encode the exact result as UTF-8, with no added newline. Records only, not batch metadata."
)


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def require_exact(actual: object, expected: object, location: str = "records") -> None:
    """Reject changed JSON types, values, field names, record counts or record order."""
    if type(actual) is not type(expected):
        raise ValueError(f"{location}: type changed")
    if isinstance(expected, dict):
        if actual.keys() != expected.keys():
            raise ValueError(f"{location}: field names changed")
        for key in expected:
            require_exact(actual[key], expected[key], f"{location}.{key}")
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError(f"{location}: length changed")
        for index, (item, original) in enumerate(zip(actual, expected, strict=True)):
            require_exact(item, original, f"{location}[{index}]")
    elif actual != expected:
        raise ValueError(f"{location}: value changed")


def duplicate_counts(records: list[dict]) -> Counter:
    # Used only for diagnostics; the payload and measurement baseline are not changed.
    return Counter(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records)


def write_json(path: Path, value: dict | list) -> None:
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if (output / "config.json").exists() or (output / "results").exists():
        parser.error("saved evidence exists; use --output-dir with a fresh directory")

    input_bytes = (ROOT / INPUT).read_bytes()
    truth_bytes = (ROOT / TRUTH).read_bytes()
    batch = TelemetryBatch.model_validate_json(input_bytes)
    truth = json.loads(truth_bytes)
    provenance = truth["provenance"]
    if "synthetic" not in batch.source or "synthetic" not in provenance:
        raise ValueError("the selected scenario no longer declares synthetic provenance")
    # Validate with M1, without serializing typed models or inserting default fields.
    parsed = parse_records(batch.records)
    before = deepcopy(batch)
    baseline = json.dumps(batch.records, ensure_ascii=False).encode("utf-8")
    compressed = compress(batch)
    payload = compressed.content.encode("utf-8")
    restored = decode_tsv(compressed.content)
    require_exact(restored, before.records)
    require_exact(batch.records, before.records)
    if batch != before:
        raise ValueError("input batch changed")
    if type(compressed.alert_time) is not type(batch.alert_time) or compressed.alert_time != batch.alert_time:
        raise ValueError("alert_time changed")
    if compressed.original_size != len(baseline) or compressed.compressed_size != len(payload):
        raise ValueError("compressor byte counts differ from the exact payloads")
    if compressed.format != "tsv" or parsed.total != len(batch.records):
        raise ValueError("unexpected format or validated record count")
    rows = list(csv.reader(io.StringIO(compressed.content, newline=""), delimiter="\t"))
    header = list(dict.fromkeys(key for record in batch.records for key in record))
    if rows[0] != header or len(rows) != len(batch.records) + 1:
        raise ValueError("shared header or row count changed")
    multiplicities = duplicate_counts(before.records)
    if duplicate_counts(restored) != multiplicities:
        raise ValueError("duplicate multiplicities changed")

    status = git("status", "--porcelain=v1", "--untracked-files=all").decode("utf-8")
    patch = git("diff", "HEAD", "--binary")
    source_paths = [
        "src/argus/orchestration/service.py",
        "src/argus/context/ingest.py",
        "src/argus/contracts/telemetry.py",
        "pyproject.toml",
        "tests/unit/orchestration/test_service.py",
        "tests/integration/test_m1_reads_m4_output.py",
    ]
    configuration = {
        "command": f"python {Path(__file__).resolve().relative_to(ROOT).as_posix()}",
        "actual_python_invocation": ".venv/Scripts/python.exe"
        if sys.platform == "win32"
        else ".venv/bin/python",
        "source_commit": git("rev-parse", "HEAD").decode().strip(),
        "branch": git("branch", "--show-current").decode().strip(),
        "upstream": git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").decode().strip(),
        "source_state": "uncommitted changes present" if status else "clean working tree",
        "uncommitted_changes": bool(status),
        "git_status_at_run_start": status.splitlines(),
        "source_note": (
            "The commit alone does not identify dirty source. See source hashes and source_changes.patch."
        ),
        "source_changes_patch_sha256": sha256(patch),
        "source_file_sha256": {name: sha256((ROOT / name).read_bytes()) for name in source_paths},
        "runner_sha256": sha256(Path(__file__).read_bytes()),
        "python": sys.version,
        "platform": platform.platform(),
        "pydantic_version": version("pydantic"),
        "run_time_utc": datetime.now(UTC).isoformat(),
        "input": INPUT.as_posix(),
        "input_sha256": sha256(input_bytes),
        "provenance_source": TRUTH.as_posix(),
        "provenance_source_sha256": sha256(truth_bytes),
        "data_type": "synthetic",
        "provenance": provenance,
        "baseline_serialization": BASELINE_RULE,
        "byte_reduction_formula": "100 * (original_utf8_bytes - tsv_utf8_bytes) / original_utf8_bytes",
        "model": "None; no model calls",
        "token_counting": "not performed; not required for PP1 byte evaluation",
    }
    summary = {
        "input": INPUT.as_posix(),
        "source": batch.source,
        "data_type": "synthetic",
        "provenance": provenance,
        "sample_count": 1,
        "record_count": len(batch.records),
        "record_counts_by_kind": dict(Counter(record["kind"] for record in batch.records)),
        "baseline_serialization": BASELINE_RULE,
        "original_size_utf8_bytes": len(baseline),
        "compressed_size_utf8_bytes": len(payload),
        "byte_reduction_percentage": 100 * (len(baseline) - len(payload)) / len(baseline)
        if baseline
        else None,
        "baseline_sha256": sha256(baseline),
        "tsv_sha256": sha256(payload),
        "format": compressed.format,
        "header": header,
        "shared_header_count": 1,
        "all_records_and_exact_values_types_preserved": True,
        "field_names_preserved": True,
        "record_order_preserved": True,
        "duplicate_multiplicities_preserved": True,
        "exact_duplicate_groups_in_input": sum(count > 1 for count in multiplicities.values()),
        "extra_exact_duplicate_records_in_input": sum(count - 1 for count in multiplicities.values()),
        "duplicate_note": (
            "No rows are added for evaluation; targeted M4 tests separately exercise exact duplicates."
        ),
        "input_batch_unchanged": True,
        "m1_contract_validation_passed": True,
        "alert_time_preserved": True,
        "alert_time": batch.alert_time.isoformat() if batch.alert_time is not None else None,
        "token_measurements": "not performed",
        "claims": "one synthetic sample; byte sizes only",
    }

    commands = [
        (
            "targeted_m4_m1",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/orchestration/test_service.py",
                "tests/integration/test_m1_reads_m4_output.py",
            ],
        ),
        ("ruff_check", [sys.executable, "-m", "ruff", "check", "."]),
        ("ruff_format_check", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("git_diff_check", ["git", "diff", "--check"]),
    ]
    checks = []
    logs = {}
    for name, command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, check=False, timeout=60)
        checks.append(
            {
                "name": name,
                "command": ["python", *command[1:]] if command[0] == sys.executable else command,
                "exit_code": result.returncode,
                "stdout": f"results/{name}.stdout.txt",
                "stderr": f"results/{name}.stderr.txt",
            }
        )
        logs[f"{name}.stdout.txt"] = result.stdout
        logs[f"{name}.stderr.txt"] = result.stderr
        print(name, "exit", result.returncode)
    verification = {
        "checks": checks,
        "full_suite": {
            "status": "blocked; not run in this evaluation",
            "test": "tests/unit/safety/test_sandbox.py::test_timeout_returns_no_result",
            "prior_investigation": (
                "Windows Python 3.12.10: exceeded a 15-second external limit; "
                "worker remained alive after launcher termination. No M4 modules loaded."
            ),
        },
        "default_demo": {
            "status": "not run; existing fixture remains incompatible with contract v1",
            "input": "data/fixtures/telemetry_sample.json",
            "issues": [
                "metric missing timestamp",
                "log missing timestamp and severity",
                "unsupported kind: event",
            ],
        },
    }
    # Save outputs once. Reproduction must use a fresh output directory.
    output.mkdir(parents=True, exist_ok=True)
    results = output / "results"
    results.mkdir()
    (results / "input.telemetry.json").write_bytes(input_bytes)
    (results / "input.ground_truth.json").write_bytes(truth_bytes)
    (results / "baseline.json").write_bytes(baseline)
    (results / "telemetry.tsv").write_bytes(payload)
    (results / "source_changes.patch").write_bytes(patch)
    for name, content in logs.items():
        (results / name).write_bytes(content)
    write_json(output / "config.json", configuration)
    write_json(results / "summary.json", summary)
    write_json(results / "checks.json", verification)
    print(json.dumps(summary, indent=2))
    return int(any(check["exit_code"] != 0 for check in checks))


if __name__ == "__main__":
    raise SystemExit(main())
