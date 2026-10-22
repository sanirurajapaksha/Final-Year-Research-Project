"""TRAJECTORY: one JSON line per thing the loop did, so any run can be replayed, explained and compared.

Written from the finished LoopResult, so the loop itself stays free of logging code.
Each line carries `run`, so many runs (e.g. greedy vs ach_rca on the same incident) share one file.
With a real LLM the log also has the model and prompt versions (start line), one `llm_call` line per
call (task, prompt version, prompt hash, tokens, status, raw reply), and in the summary how many
hypotheses each source drafted: enough to repeat a run, explain it, and count what it cost.
"""

import json
import time
from collections import Counter
from pathlib import Path

from argus.diagnosis.core.belief import H0
from argus.diagnosis.core.models import DiagContext
from argus.diagnosis.loop.controller import Controller, LoopResult
from argus.diagnosis.prompts import PROMPTS


def run_logged(
    controller: Controller, ctx: DiagContext, run: str, path: Path | None = None
) -> tuple[LoopResult, dict]:
    """Run the loop, time it, optionally append its trajectory to `path`. Returns (result, summary)."""
    before = len(getattr(controller.llm, "calls", []))  # the same LLM may already have served other runs
    start = time.perf_counter()
    result = controller.run(ctx)
    elapsed_ms = (time.perf_counter() - start) * 1000
    calls = list(getattr(controller.llm, "calls", []))[before:]
    events = to_events(result, controller, run, elapsed_ms, calls)
    if path is not None:
        with Path(path).open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(e) + "\n" for e in events)
    return result, events[-1]


def to_events(
    result: LoopResult, controller: Controller, run: str, elapsed_ms: float, calls: list[dict] | None = None
) -> list[dict]:
    cfg = controller.cfg
    events = [
        {
            "run": run,
            "event": "start",
            "model": getattr(controller.llm, "model", None),  # None: no LLM, everything ran on rules
            "prompt_versions": {task: t.version for task, t in PROMPTS.items()},
            "config": {
                "k": cfg.k,
                "use_h0": cfg.use_h0,
                "use_eig": cfg.use_eig,
                "backtracking": cfg.backtracking,
                "graph_priors": cfg.graph_priors,
                "per_component": cfg.per_component,
                "generator": cfg.generator,
            },
        }
    ]
    events += [{"run": run, "event": "hypothesis", **h.model_dump()} for h in result.hypotheses.values()]
    evidence = {e.id: e for e in result.evidence}
    for step in result.belief.history:
        line = {"run": run, "event": step["event"], "belief": _rounded(step["belief"])}
        if "evidence" in step:  # an update: say which read caused it and what the LLM concluded
            e = evidence[step["evidence"]]
            line.update(
                evidence=e.id,
                hyp_id=e.hyp_id,
                command=e.command,
                ok=e.ok,
                output_chars=len(e.output),
                verdicts=step["verdicts"],
            )
        if "added" in step:
            line["added"] = step["added"]
        events.append(line)
    events += [{"run": run, "event": "llm_call", **call} for call in calls or []]
    events.append(summary(result, run, elapsed_ms))
    return events


def summary(result: LoopResult, run: str, elapsed_ms: float) -> dict:
    """The one line an experiment table needs: answer, confidence, cost."""
    ranked = [(h, p) for h, p in result.belief.ranked() if h != H0]
    top, p = ranked[0] if ranked else (None, 0.0)
    return {
        "run": run,
        "event": "finish",
        "top": top,
        "top_label": result.hypotheses[top].label() if top else None,
        "p": round(p, 4),
        "stop_reason": result.report.stop_reason,
        "low_confidence": result.report.low_confidence,
        "reads": len(result.evidence),
        "rehypothesized": sum(1 for s in result.belief.history if s["event"] == "rehypothesize"),
        "elapsed_ms": round(elapsed_ms, 2),
        "usage": result.report.usage,
        "sources": dict(Counter(h.source for h in result.hypotheses.values())),
    }


def _rounded(belief: dict[str, float]) -> dict[str, float]:
    return {h: round(p, 4) for h, p in belief.items()}
