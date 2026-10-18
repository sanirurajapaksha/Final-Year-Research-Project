"""ADAPT step: M1's SemanticContext -> M2's DiagContext (candidates, failing path, symptoms).

Two modes, picked by what M1 sent:
- graph: M1 F2 gave `failing_services` and `dependencies`. The deepest failing service gets 1.5,
  the rest of the failing path 1.0, every other known service 0.5.
- signals: no graph yet (today's M1 is Stage 1 only). Every service with a kept signal gets 1.0,
  and the one with the most signals gets 1.5.
An empty context gives no candidates; `notes` says why, so the report can explain it.
"""

from collections import Counter, deque

from argus.contracts import SemanticContext
from argus.diagnosis.core.models import Candidate, DiagContext

DEEPEST = 1.5
ON_PATH = 1.0
OTHER = 0.5


def adapt(context: SemanticContext, namespace: str) -> DiagContext:
    """Turn M1's context into what the loop diagnoses from. Pure: no I/O, no LLM."""
    if context.failing_services and context.dependencies:
        path = failing_path(context)
        candidates = _graph_candidates(context, path)
    else:
        path = []
        candidates = _signal_candidates(context)
    return DiagContext(
        namespace=namespace,
        candidates=candidates,
        symptoms=_symptoms(context),
        failing_path=path,
        notes=context.notes,
    )


def failing_path(context: SemanticContext) -> list[str]:
    """Failing services ordered caller -> callee, starting at the entry point when known."""
    failing = set(context.failing_services)
    callees = _failing_callees(context)
    if context.entry_point in failing:
        starts = [context.entry_point]
    else:  # no entry point: start from failing services no other failing service calls
        called = {c for cs in callees.values() for c in cs}
        starts = sorted(failing - called) or sorted(failing)
    order: list[str] = []
    queue = deque(starts)
    while queue:  # breadth-first, so a service appears after everything that calls it
        service = queue.popleft()
        if service in order:
            continue
        order.append(service)
        queue.extend(sorted(callees.get(service, set())))
    # A failing service the walk can't reach (e.g. an edge M1 missed) still belongs on the path.
    return order + sorted(failing - set(order))


def _failing_callees(context: SemanticContext) -> dict[str, set[str]]:
    """Dependency edges where both ends are failing: who each failing service calls that also fails."""
    failing = set(context.failing_services)
    callees: dict[str, set[str]] = {}
    for caller, callee in context.dependencies:
        if caller in failing and callee in failing and caller != callee:
            callees.setdefault(caller, set()).add(callee)
    return callees


def _graph_candidates(context: SemanticContext, path: list[str]) -> list[Candidate]:
    callees = _failing_callees(context)
    # Deepest = a failing service whose own callees are all healthy, so the errors start there.
    deepest = {s for s in path if not callees.get(s)} or {path[-1]}  # a cycle has no leaf
    weights = {s: DEEPEST if s in deepest else ON_PATH for s in path}
    for service in _known_services(context):
        weights.setdefault(service, OTHER)
    return _ranked(weights, path)


def _signal_candidates(context: SemanticContext) -> list[Candidate]:
    counts = Counter(signal.service for signal in context.kept_signals)
    weights = {service: ON_PATH for service in counts}
    for service in context.failing_services:
        weights.setdefault(service, ON_PATH)
    if counts:
        top = max(counts.values())
        for service, n in counts.items():
            if n == top:  # a tie keeps every tied service at the top; the loop's tests decide
                weights[service] = DEEPEST
    for service in _known_services(context):
        weights.setdefault(service, OTHER)
    return _ranked(weights, [])


def _known_services(context: SemanticContext) -> list[str]:
    """Every service M1 mentioned anywhere, in a stable order."""
    names = [*context.services, *(node.name for node in context.nodes)]
    names += [s for edge in context.dependencies for s in edge]
    names += [signal.service for signal in context.kept_signals]
    return list(dict.fromkeys(names))


def _ranked(weights: dict[str, float], path: list[str]) -> list[Candidate]:
    """Highest weight first; ties keep failing-path order, then go alphabetically."""
    position = {s: i for i, s in enumerate(path)}
    order = sorted(weights, key=lambda s: (-weights[s], position.get(s, len(path)), s))
    return [Candidate(service=s, weight=weights[s]) for s in order]


def _symptoms(context: SemanticContext) -> list[str]:
    """What the LLM and the report see: M1's symptoms, then its anomaly lines, without repeats."""
    lines = context.anomalies or [
        f"{signal.service}: {signal.name} ({signal.evidence})" for signal in context.kept_signals
    ]
    return list(dict.fromkeys([*context.symptoms, *lines]))
