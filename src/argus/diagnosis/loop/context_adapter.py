"""ADAPT step: M1's SemanticContext -> M2's DiagContext (candidates, failing path, symptoms).

Two modes, picked by what M1 sent:
- graph: M1 F2 gave `failing_services` and `dependencies`. The deepest failing service gets 1.5,
  the rest of the failing path 1.0, every other known service 0.5. The failing path follows M1 F2:
  failing services plus their callers up to the entry point, even callers that report no error.
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
    """M1's failing path: failing services plus their callers up to the entry point, caller -> callee.

    A caller is on the path even when it reports no error itself (e.g. a gateway that catches a
    downstream error), because the failing requests went through it.
    """
    failing = set(context.failing_services)
    on_path = _with_upstream_callers(context, failing)
    callees = _callees_within(context, on_path)
    if context.entry_point in on_path:
        starts = [context.entry_point]
    else:  # no entry point: start from path services no other path service calls
        called = {c for cs in callees.values() for c in cs}
        starts = sorted(on_path - called) or sorted(on_path)
    order: list[str] = []
    queue = deque(starts)
    while queue:  # breadth-first, so a service appears after everything that calls it
        service = queue.popleft()
        if service in order:
            continue
        order.append(service)
        queue.extend(sorted(callees.get(service, set())))
    # A failing service the walk can't reach (e.g. an edge M1 missed) still belongs on the path.
    # A healthy caller the entry point doesn't reach is not on the failing requests' route, so it stays off.
    return order + sorted(failing - set(order))


def _with_upstream_callers(context: SemanticContext, failing: set[str]) -> set[str]:
    """The failing services and every service calling them, directly or not, stopping at the entry point."""
    callers: dict[str, set[str]] = {}
    for caller, callee in context.dependencies:
        if caller != callee:
            callers.setdefault(callee, set()).add(caller)
    found = set(failing)
    queue = deque(failing)
    while queue:
        service = queue.popleft()
        if service == context.entry_point:  # the requests entered here, so nothing above it is on the path
            continue
        for caller in callers.get(service, set()) - found:
            found.add(caller)
            queue.append(caller)
    return found


def _callees_within(context: SemanticContext, services: set[str]) -> dict[str, set[str]]:
    """Dependency edges with both ends in `services`: who each of them calls inside that set."""
    callees: dict[str, set[str]] = {}
    for caller, callee in context.dependencies:
        if caller in services and callee in services and caller != callee:
            callees.setdefault(caller, set()).add(callee)
    return callees


def _graph_candidates(context: SemanticContext, path: list[str]) -> list[Candidate]:
    failing = set(context.failing_services)
    callees = _callees_within(context, failing)
    # Deepest = a failing service whose own callees are all healthy, so the errors start there.
    # Only failing services qualify: a healthy caller on the path never originates the errors.
    failing_in_order = [s for s in path if s in failing]
    # A failing cycle has no leaf, so fall back to the last failing service on the path.
    deepest = {s for s in failing_in_order if not callees.get(s)} or {failing_in_order[-1]}
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
