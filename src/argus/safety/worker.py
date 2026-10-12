"""Solver worker, run only as a separate process by sandbox.py:

    python -m argus.safety.worker < request.json

Reads one request as JSON on stdin, prints one result as JSON on stdout, exits 0.
On any error it prints the error to stderr and exits 2; the sandbox treats that as "no result".
It imports only the compiler (not the rest of Argus) to keep start-up small.
"""

import json
import sys

from argus.safety.compiler import solve


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        result = solve(request)
    except Exception as exc:  # any failure must reach the parent as "no result", never as a verdict
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
