"""Save actual fixture output and local check results for the minimal F1 slice."""

import json
import subprocess
import sys
from pathlib import Path

from argus.contracts import TelemetryBatch
from argus.orchestration.service import compress

ROOT = Path(__file__).resolve().parents[2]
RUN = Path(__file__).resolve().parent
RESULTS = RUN / "results"
RESULTS.mkdir(exist_ok=True)

fixture = "data/fixtures/telemetry_sample.json"
batch = TelemetryBatch.model_validate_json((ROOT / fixture).read_text(encoding="utf-8"))
compressed = compress(batch)
(RESULTS / "telemetry_sample.tsv").write_bytes(compressed.content.encode("utf-8"))
summary = {
    "input_fixture_path": fixture,
    "input_description": "Hand-written illustrative fixture; not a benchmark or live telemetry.",
    "sample_count": 1,
    "record_count": len(batch.records),
    "output_format": compressed.format,
    "original_size_utf8_bytes": compressed.original_size,
    "compressed_size_utf8_bytes": compressed.compressed_size,
    "original_size_serialization_convention": (
        'len(json.dumps(batch.records, ensure_ascii=False).encode("utf-8")); '
        "all other json.dumps options use Python defaults, including sort_keys=False, "
        "indent=None, and separators=(', ', ': '). This measures records only, "
        "not the fixture file or batch metadata."
    ),
}
(RESULTS / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
config = {
    "command": ".venv\\Scripts\\python.exe experiments/2026-10-10_m4_minimal_f1/run.py",
    "python_executable": sys.executable,
    "python_version": sys.version,
    "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    "source_state": "Uncommitted work; the base commit alone does not identify this implementation.",
    "input_fixture_path": fixture,
    "model": "None; no model calls are made.",
}
(RUN / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
commands = [
    ("pytest", [sys.executable, "-m", "pytest"]),
    ("ruff_check", [sys.executable, "-m", "ruff", "check", "."]),
    ("ruff_format_check", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ("git_diff_check", ["git", "diff", "--check"]),
]
checks = []
for name, command in commands:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
    (RESULTS / f"{name}.stdout.txt").write_bytes(result.stdout)
    (RESULTS / f"{name}.stderr.txt").write_bytes(result.stderr)
    checks.append({"name": name, "command": command, "exit_code": result.returncode})
    print(name, result.returncode)
    print(result.stdout.decode("utf-8", errors="replace"))
(RESULTS / "checks.json").write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2))
