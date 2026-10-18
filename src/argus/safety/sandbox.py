"""Step 3: sandboxed Z3 runtime.

Runs the solver worker (worker.py) in a separate process:
- wall-clock timeout: the process is killed after `timeout_s`;
- on Linux/macOS also a CPU-time limit and an address-space (memory) cap, set in the child
  before it starts. Windows has no equivalent in the standard library, so there only the
  timeout applies. CI runs on Linux, so the limits are tested there; results record the platform;
- Z3's own timeout is set a little lower than the process timeout, so Z3 normally answers
  `unknown` before the process is killed.

Any problem (timeout, crash, non-zero exit, unreadable output) returns no result. The gate
treats that as BLOCK. No generated code runs here: the worker is a fixed module that reads data.
"""

import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

if os.name == "posix":
    import resource

Z3_TIMEOUT_SHARE = 0.8


@dataclass(frozen=True)
class SandboxOutcome:
    result: dict[str, Any] | None
    error: str | None = None


def z3_timeout_ms(timeout_s: float) -> int:
    return max(1, int(timeout_s * 1000 * Z3_TIMEOUT_SHARE))


def _limit_child(timeout_s: float, memory_mb: int):
    def apply() -> None:
        cpu_seconds = max(1, math.ceil(timeout_s))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        memory_bytes = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

    return apply


def run(request: dict[str, Any], timeout_s: float, memory_mb: int) -> SandboxOutcome:
    preexec = _limit_child(timeout_s, memory_mb) if os.name == "posix" else None
    try:
        process = subprocess.run(
            [sys.executable, "-m", "argus.safety.worker"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            preexec_fn=preexec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SandboxOutcome(None, f"timeout after {timeout_s} s")
    except OSError as exc:
        return SandboxOutcome(None, f"could not start the worker: {exc}")

    if process.returncode != 0:
        detail = process.stderr.strip().splitlines()[-1] if process.stderr.strip() else "no error output"
        return SandboxOutcome(None, f"worker exited with code {process.returncode}: {detail}")

    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError:
        return SandboxOutcome(None, "worker output is not valid JSON")
    if not isinstance(result, dict):
        return SandboxOutcome(None, "worker output is not a JSON object")
    return SandboxOutcome(result)
