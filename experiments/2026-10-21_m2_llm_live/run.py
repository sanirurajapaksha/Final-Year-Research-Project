"""M2 LLM steps against a real model: the live-test checks, repeated, plus end-to-end runs.

Run from the repository root, with ARGUS_LLM_API_KEY set (it costs a few dozen short calls per model):
    python experiments/2026-10-21_m2_llm_live/run.py --model deepseek/deepseek-v4-flash-0731
    python experiments/2026-10-21_m2_llm_live/run.py --model google/gemini-2.5-flash-lite
Writes results/<model>/ next to this file. Don't overwrite an earlier run: copy this script to a new
dated folder instead.

Every check uses scenario_01's canned reads (data/fixtures/m2/scenario_01/reads.json), which are
hand-written: a read M2 asks for that isn't in that file fails, exactly as on the dashboard.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from argus.contracts import ProposedAction, SemanticContext
from argus.diagnosis.core.config import preset
from argus.diagnosis.core.models import Candidate, DiagContext, Evidence, HypothesisSpec
from argus.diagnosis.demo import scenario_reads
from argus.diagnosis.loop.context_adapter import adapt
from argus.diagnosis.loop.controller import Controller, ScoreAnswer
from argus.diagnosis.loop.fixes import patch_env_command
from argus.diagnosis.loop.llm_fixer import FixProposer
from argus.diagnosis.loop.llm_generator import LLMGenerator
from argus.diagnosis.loop.report import ReportWriter
from argus.diagnosis.loop.scorer import RuleScorer
from argus.diagnosis.loop.trajectory import run_logged
from argus.diagnosis.ports.openrouter import OpenRouterLLM
from argus.diagnosis.prompts import PROMPTS
from argus.diagnosis.service import to_result

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CART_ADDR = ROOT / "data" / "fixtures" / "m2" / "contexts" / "cart_addr.json"
DEPLOYMENT = "kubectl get deployment cart -n default -o json"
EXPECTED_FIX = patch_env_command("cart", "CART_ADDR", "redis-cart:6379", "default")
SCORE_HYPOTHESES = {
    "H1": "cart [app-config] missing or wrong dependency address env var | expects: CART_ADDR absent",
    "H2": "cart [k8s-network] Service selects no ready pods | expects: no ready addresses",
    "H3": "cart [resources] container OOMKilled or crash-looping | expects: OOMKilled or CrashLoop",
}
SCORE_EXPECTED = {
    DEPLOYMENT: ("H1", "strong-support"),
    "kubectl get endpoints cart -n default": ("H2", "strong-refute"),
    "kubectl describe pods -n default -l app=cart": ("H3", "strong-refute"),
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def context() -> SemanticContext:
    return SemanticContext.model_validate(json.loads(CART_ADDR.read_text(encoding="utf-8"))["context"])


def keep_calls(llm: OpenRouterLLM, check: str, run: int, out) -> None:
    """Every call this LLM made, as llm_call lines tagged with the check and run."""
    for call in llm.calls:
        out.write(json.dumps({"check": check, "run": run, "event": "llm_call", **call}) + "\n")


def check_score(model, repeats, calls_out) -> list[dict]:
    reads = scenario_reads()
    rows = []
    for run in range(repeats):
        llm = OpenRouterLLM(model)
        for command, (hyp, expected) in SCORE_EXPECTED.items():
            try:
                got = llm.structured(
                    "score",
                    ScoreAnswer,
                    command=command,
                    output=reads.run(command).output,
                    hypotheses=SCORE_HYPOTHESES,
                ).by_id()
            except Exception as exc:  # noqa: BLE001 - a failed call is a result here, not a crash
                got = {"error": f"{type(exc).__name__}: {exc}"}
            rows.append({"run": run, "command": command, "verdicts": got, "pass": got.get(hyp) == expected})
        keep_calls(llm, "score", run, calls_out)
    return rows


def check_draft(model, repeats, calls_out) -> list[dict]:
    ctx = adapt(context(), "default", scheme="hop")
    rows = []
    for run in range(repeats):
        llm = OpenRouterLLM(model)
        hyps = LLMGenerator(llm).draft(ctx, k=3)
        from_llm = [h for h in hyps if h.source == "llm"]
        rows.append(
            {
                "run": run,
                "hypotheses": [h.model_dump() for h in hyps],
                "pass": ("cart", "app-config") in {(h.component, h.layer) for h in from_llm},
            }
        )
        keep_calls(llm, "draft", run, calls_out)
    return rows


def check_fix(model, repeats, calls_out) -> list[dict]:
    ctx = adapt(context(), "default", scheme="hop")
    reads = scenario_reads()
    top = HypothesisSpec(
        id="H1",
        component="cart",
        layer="app-config",
        fault="CART_ADDR env var missing",
        test=DEPLOYMENT,
        expected="no CART_ADDR in the cart container env",
    )
    e1 = Evidence(id="E1", hyp_id="H1", command=DEPLOYMENT, output=reads.run(DEPLOYMENT).output, ok=True)
    rows = []
    for run in range(repeats):
        llm = OpenRouterLLM(model)
        outcome = FixProposer(llm, reads).propose(top, ctx, [e1], {})
        command = outcome.action.command if outcome.action else None
        rows.append(
            {
                "run": run,
                "source": outcome.source,
                "command": command,
                "note": outcome.note,
                "tries": sum(1 for c in llm.calls if c["task"] == "fix"),
                "pass": outcome.source == "llm" and command == EXPECTED_FIX,
            }
        )
        keep_calls(llm, "fix", run, calls_out)
    return rows


def check_report(model, repeats, calls_out) -> list[dict]:
    ctx = DiagContext(
        namespace="default",
        candidates=[Candidate(service="cart")],
        symptoms=["cart: log_error (failed to connect to redis: CART_ADDR environment variable not set)"],
    )
    top = HypothesisSpec(
        id="H1", component="cart", layer="app-config", fault="CART_ADDR env var missing", test=DEPLOYMENT
    )
    e1 = Evidence(
        id="E1",
        hyp_id="H1",
        command=DEPLOYMENT,
        output='{"containers": [{"name": "cart", "env": []}]}',
        ok=True,
    )
    fix = ProposedAction(command=EXPECTED_FIX, is_write=True)
    rows = []
    for run in range(repeats):
        llm = OpenRouterLLM(model)
        text, source = ReportWriter(llm).write(
            top, 0.85, True, "confident", [e1], {"E1": "strong-support"}, fix, "", ctx
        )
        rows.append(
            {"run": run, "source": source, "words": len(text.split()), "text": text, "pass": source == "llm"}
        )
        keep_calls(llm, "report", run, calls_out)
    return rows


def check_end_to_end(model, repeats, calls_out, trajectory: Path) -> list[dict]:
    """The dashboard's path with the LLM on: adapt -> loop (logged) -> fix -> report."""
    rows = []
    for run in range(repeats):
        llm = OpenRouterLLM(model)
        reads = scenario_reads()
        cfg = preset("A5-hop", namespace="default")
        ctx = adapt(context(), cfg.namespace, scheme="hop")
        controller = Controller(cfg, llm=llm, reads=reads, scorer=RuleScorer())
        result, finish = run_logged(controller, ctx, f"e2e-{run}", trajectory)
        diagnosis = to_result(result, ctx, {}, FixProposer(llm, reads, cfg.max_revisions))
        writes = [a.command for a in diagnosis.actions if a.is_write]
        rows.append(
            {
                "run": run,
                "stop_reason": result.report.stop_reason,
                "top": finish["top_label"],
                "p": finish["p"],
                "reads": [{"id": e.id, "command": e.command, "ok": e.ok} for e in result.evidence],
                "writes": writes,
                "report_source": result.report.report_source,
                "report_text": result.report.report_text,
                "usage": dict(llm.usage),
                "pass_same_as_rules": writes == [EXPECTED_FIX],
            }
        )
        keep_calls(llm, "end_to_end", run, calls_out)
    return rows


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--model", default=os.environ.get("ARGUS_LLM_MODEL", ""))
    args.add_argument("--repeats", type=int, default=3)
    args.add_argument("--fix-repeats", type=int, default=5)
    a = args.parse_args()
    if not os.environ.get("ARGUS_LLM_API_KEY") or not a.model:
        sys.exit("set ARGUS_LLM_API_KEY and pass --model (or set ARGUS_LLM_MODEL)")

    out = HERE / "results" / a.model.replace("/", "__")
    out.mkdir(parents=True, exist_ok=False)  # never overwrite an earlier run
    with (out / "llm_calls.jsonl").open("w", encoding="utf-8") as calls:
        checks = {
            "score": check_score(a.model, a.repeats, calls),
            "draft": check_draft(a.model, a.repeats, calls),
            "fix": check_fix(a.model, a.fix_repeats, calls),
            "report": check_report(a.model, a.repeats, calls),
            "end_to_end": check_end_to_end(a.model, a.repeats, calls, out / "trajectories.jsonl"),
        }
    for name, rows in checks.items():
        (out / f"{name}.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    summary = {
        "model": a.model,
        "pass_counts": {
            name: f"{sum(r.get('pass', r.get('pass_same_as_rules', False)) for r in rows)}/{len(rows)}"
            for name, rows in checks.items()
        },
        "fix_tries": [r["tries"] for r in checks["fix"]],
        "end_to_end_stop": [r["stop_reason"] for r in checks["end_to_end"]],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    config = {
        "command": " ".join(["python", *sys.argv]),
        "commit": git("rev-parse", "HEAD"),
        "uncommitted_tracked_changes": bool(git("status", "--porcelain", "--untracked-files=no")),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "model": a.model,
        "prompt_versions": {task: t.version for task, t in PROMPTS.items()},
        "inputs": ["data/fixtures/m2/contexts/cart_addr.json", "data/fixtures/m2/scenario_01/reads.json"],
    }
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
