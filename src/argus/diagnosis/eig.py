"""Expected information gain: pick the read-only test that best separates the hypotheses."""

from math import log2

# How the Test Designer's words map to P(test shows the anomaly | hypothesis is true).
PRED = {"very_likely": 0.9, "likely": 0.7, "unsure": 0.5, "unlikely": 0.3, "very_unlikely": 0.1}


def entropy(ps) -> float:
    return -sum(p * log2(p) for p in ps if p > 0)


def eig(belief: dict[str, float], p_pos: dict[str, float]) -> float:
    """belief: hypothesis -> probability (sums to 1); p_pos: hypothesis -> P(test positive | hypothesis)."""
    pp = sum(belief[h] * p_pos[h] for h in belief)
    pn = 1.0 - pp
    post_p = {h: belief[h] * p_pos[h] / pp for h in belief} if pp > 0 else belief
    post_n = {h: belief[h] * (1 - p_pos[h]) / pn for h in belief} if pn > 0 else belief
    return entropy(belief.values()) - (pp * entropy(post_p.values()) + pn * entropy(post_n.values()))


def rank_tests(
    belief: dict[str, float],
    matrix: dict[str, dict[str, float]],
    cost: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    """matrix: test id -> {hypothesis -> P(positive | hypothesis)}. Returns [(test id, score)], best first."""
    cost = cost or {}
    scored = [(t, eig(belief, m) / cost.get(t, 1.0)) for t, m in matrix.items()]
    return sorted(scored, key=lambda x: -x[1])
