"""ADAPT step: M1's SemanticContext -> M2's DiagContext (candidates, failing path, symptoms).

Two modes, picked by what M1 sent:
- graph: M1 F2 gave `failing_services` and `dependencies`. The failing path follows M1 F2: failing
  services plus their callers up to the entry point, even callers that report no error. The deepest
  failing service is the origin: errors start there and climb up the call chain. Two weight schemes:
    almanac - origin 1.5, the rest of the failing path 1.0, every other known service 0.5.
    hop     - graded by hops up from the origin (0: 1.5, 1: 1.0, 2: 0.7, 3+: 0.5), because the
              further up a service is, the more likely it only shows someone else's failure; plus
              quiet dependencies at 1.0: services the origin calls, or names in its errors, that
              report nothing themselves (a dead redis only shows up in its caller's logs).
- signals: no graph (M1 Stage 1 only). Every service with a kept signal gets 1.0,
  and the one with the most signals gets 1.5. Both schemes are the same here.
An empty context gives no candidates; `notes` says why, so the report can explain it.
"""

import re
from collections import Counter, deque
from typing import Literal

from argus.contracts import SemanticContext
from argus.diagnosis.core.models import Candidate, DiagContext, Role

DEEPEST = 1.5
ON_PATH = 1.0
OTHER = 0.5

HOP_UP = {0: 1.5, 1: 1.0, 2: 0.7}  # hops up from the origin -> weight; further up gets FAR
FAR = 0.5
QUIET = 1.0

# A service named in an error line: "failed to connect to redis", "dial tcp: lookup redis-cart".
NAMED_SERVICE = re.compile(
    r"(?:connect(?:ing)?\s+to|lookup|dial\s+tcp:?|desc\s*=)\s+([a-z][a-z0-9-]*[a-z0-9])"
)
NOT_A_SERVICE = {"the", "a", "an", "it", "server", "host", "service", "upstream", "localhost", "tcp"}

Scheme = Literal["almanac", "hop"]


def adapt(context: SemanticContext, namespace: str, scheme: Scheme = "almanac") -> DiagContext:
    """Turn M1's context into what the loop diagnoses from. Pure: no I/O, no LLM."""
    if context.failing_services and context.dependencies:
        path = failing_path(context)
        candidates = _graph_candidates(context, path, scheme)
    else:
        path = []
        candidates = _signal_candidates(context)
    return DiagContext(
        namespace=namespace,
        candidates=candidates,
        symptoms=_symptoms(context),
        failing_path=path,
        node_status={n.name: n.k8s_status for n in context.nodes if n.k8s_status},
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


def _graph_candidates(context: SemanticContext, path: list[str], scheme: Scheme) -> list[Candidate]:
    failing = set(context.failing_services)
    callees = _callees_within(context, set(path))
    # Deepest = a failing service with no failing service below it, so the errors start there.
    # "Below" follows the whole path, healthy hops included (frontend -> gateway -> cart: cart is below).
    # Only failing services qualify: a healthy caller on the path never originates the errors.
    failing_in_order = [s for s in path if s in failing]
    deepest = {s for s in failing_in_order if not _descendants(s, callees) & failing}
    # A failing cycle has no leaf, so fall back to the last failing service on the path.
    deepest = deepest or {failing_in_order[-1]}

    hops = _hops_up(deepest, callees)
    roles: dict[str, tuple[Role, int | None]] = {
        s: ("origin", 0) if s in deepest else ("upstream", hops.get(s)) for s in path
    }
    # Names read from log text only join under the hop scheme, so "almanac" stays exactly the Almanac's.
    for service in _quiet_dependencies(context, deepest, set(path), from_logs=scheme == "hop"):
        roles.setdefault(service, ("quiet-dependency", 1))
    for service in _known_services(context):
        roles.setdefault(service, ("other", None))

    weigh = _hop_weight if scheme == "hop" else _almanac_weight
    candidates = {s: Candidate(service=s, weight=weigh(r, h), role=r, hops=h) for s, (r, h) in roles.items()}
    return _ranked(candidates, path)


def _almanac_weight(role: Role, hops: int | None) -> float:
    if role == "origin":
        return DEEPEST
    return ON_PATH if role == "upstream" else OTHER


def _hop_weight(role: Role, hops: int | None) -> float:
    if role == "origin":
        return DEEPEST
    if role == "upstream":
        # A path service the backwards walk can't reach (an edge M1 missed) keeps the plain path weight.
        return ON_PATH if hops is None else HOP_UP.get(hops, FAR)
    return QUIET if role == "quiet-dependency" else OTHER


def _hops_up(origins: set[str], callees: dict[str, set[str]]) -> dict[str, int]:
    """Hops from each path service down to the nearest origin, walking the path's calls backwards."""
    callers: dict[str, set[str]] = {}
    for caller, called in callees.items():
        for callee in called:
            callers.setdefault(callee, set()).add(caller)
    hops = dict.fromkeys(origins, 0)
    queue = deque(sorted(origins))
    while queue:  # breadth-first, so each service keeps its shortest distance
        service = queue.popleft()
        for caller in sorted(callers.get(service, set())):
            if caller not in hops:
                hops[caller] = hops[service] + 1
                queue.append(caller)
    return hops


def _quiet_dependencies(
    context: SemanticContext, origins: set[str], on_path: set[str], from_logs: bool
) -> list[str]:
    """One hop below the origin, reporting nothing: the origin's callees in M1's graph and, when
    `from_logs`, services its error lines name. A dead redis never logs; only its caller says so."""
    found = [callee for caller, callee in context.dependencies if caller in origins and callee not in on_path]
    if from_logs:
        known = _known_services(context)
        for signal in context.kept_signals:
            if signal.service not in origins:
                continue  # an upstream service naming something points down the path, not past the origin
            for name in NAMED_SERVICE.findall(signal.evidence):
                service = _resolve(name, known)
                if name not in NOT_A_SERVICE and service not in on_path:
                    found.append(service)
    return list(dict.fromkeys(found))


def _resolve(name: str, known: list[str]) -> str:
    """'redis' in a log line -> 'redis-cart' when M1 knows a service by that longer name."""
    if name in known:
        return name
    for service in known:
        if service.startswith(f"{name}-") or service.endswith(f"-{name}"):
            return service
    return name


def _descendants(service: str, callees: dict[str, set[str]]) -> set[str]:
    """Every service `service` reaches through `callees`, directly or not, not counting itself."""
    seen: set[str] = set()
    queue = deque(callees.get(service, set()))
    while queue:
        callee = queue.popleft()
        if callee in seen:
            continue
        seen.add(callee)
        queue.extend(callees.get(callee, set()))
    return seen - {service}


def _signal_candidates(context: SemanticContext) -> list[Candidate]:
    counts = Counter(signal.service for signal in context.kept_signals)
    candidates = {s: Candidate(service=s, weight=ON_PATH, role="has-signals") for s in counts}
    for service in context.failing_services:
        candidates.setdefault(service, Candidate(service=service, weight=ON_PATH, role="has-signals"))
    if counts:
        top = max(counts.values())
        for service, n in counts.items():
            if n == top:  # a tie keeps every tied service at the top; the loop's tests decide
                candidates[service] = Candidate(service=service, weight=DEEPEST, role="top-signals")
    for service in _known_services(context):
        candidates.setdefault(service, Candidate(service=service, weight=OTHER))
    return _ranked(candidates, [])


def _known_services(context: SemanticContext) -> list[str]:
    """Every service M1 mentioned anywhere, in a stable order."""
    names = [*context.services, *(node.name for node in context.nodes)]
    names += [s for edge in context.dependencies for s in edge]
    names += [signal.service for signal in context.kept_signals]
    return list(dict.fromkeys(names))


def _ranked(candidates: dict[str, Candidate], path: list[str]) -> list[Candidate]:
    """Highest weight first; ties keep failing-path order, then go alphabetically."""
    position = {s: i for i, s in enumerate(path)}
    order = sorted(candidates, key=lambda s: (-candidates[s].weight, position.get(s, len(path)), s))
    return [candidates[s] for s in order]


def _symptoms(context: SemanticContext) -> list[str]:
    """What the LLM and the report see: M1's symptoms, then its anomaly lines, without repeats."""
    lines = context.anomalies or [
        f"{signal.service}: {signal.name} ({signal.evidence})" for signal in context.kept_signals
    ]
    return list(dict.fromkeys([*context.symptoms, *lines]))
