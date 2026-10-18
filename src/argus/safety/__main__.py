"""Check one command with M3 and print the verdict as JSON.

    python -m argus.safety "kubectl scale deployment geo --replicas=1 -n hotel-reservation" \
        --snapshot data/fixtures/m3/snapshot_hotel_reservation.json

Exit code: 0 for APPROVE, 1 for BLOCK.
"""

import argparse
import json
from pathlib import Path

from argus.contracts import GateDecision, ProposedAction
from argus.safety.gate import check


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(prog="python -m argus.safety", description="Check one write command.")
    cli.add_argument("command", help="the exact kubectl command, quoted")
    cli.add_argument(
        "--snapshot",
        type=Path,
        help="cluster snapshot JSON (default: facts from ARGUS_M3_KUBECTL_OUTPUT or ARGUS_KUBE_CONTEXT)",
    )
    args = cli.parse_args(argv)

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8")) if args.snapshot else None
    verdict = check(ProposedAction(command=args.command, is_write=True), snapshot=snapshot)
    print(verdict.model_dump_json(indent=2))
    return 0 if verdict.decision is GateDecision.APPROVE else 1


if __name__ == "__main__":
    raise SystemExit(main())
