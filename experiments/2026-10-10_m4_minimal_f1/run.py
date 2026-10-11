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

# Use the real interpreter to run checks, but save only portable path text.
executable = Path(sys.executable).resolve()
python_command = executable.relative_to(ROOT).as_posix() if executable.is_relative_to(ROOT) else "python"
path_note = (
    "Paths normalized for portability; commands are portable representations. "
    "Subprocess output paths are normalized; other output and exit codes are preserved."
)

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
    "command": f"{python_command} {Path(__file__).resolve().relative_to(ROOT).as_posix()}",
    "python_executable": python_command,
    "path_normalization": path_note,
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
    # Replace local root/interpreter text without changing line endings or timings.
    replacements = [(sys.executable, python_command), (str(executable), python_command)]
    replacements.extend([(str(ROOT), "."), (ROOT.as_posix(), ".")])
    for stream in ("stdout", "stderr"):
        output = getattr(result, stream)
        for local_path, portable_path in replacements:
            output = output.replace(local_path.encode("utf-8"), portable_path.encode("utf-8"))
        (RESULTS / f"{name}.{stream}.txt").write_bytes(output)
    saved_command = [python_command, *command[1:]] if command[0] == sys.executable else command
    checks.append(
        {
            "name": name,
            "command": saved_command,
            "exit_code": result.returncode,
            "path_normalization": path_note,
        }
    )
    print(name, result.returncode)
    print(result.stdout.decode("utf-8", errors="replace"))
(RESULTS / "checks.json").write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2))
