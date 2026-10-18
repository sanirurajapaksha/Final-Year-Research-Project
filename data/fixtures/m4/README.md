# M4 offline routing fixture

`routing_synthetic.json` is hand-written test data, not benchmark telemetry.
All model names, costs and quality scores are synthetic. Costs use arbitrary
integer credits; scores on the 0–100 scale are not measured model accuracy.

The two tasks exercise telemetry parsing and diagnostic reasoning. Deliberately
cheap, high-scoring candidates in the wrong layer test that quality and budget
cannot override TAF task/layer eligibility. Within each eligible layer there are
two candidates, so tasks compete for a shared budget.

With the explicit `max_quality` objective:

- Budget 5: infeasible; the cheapest eligible full assignment costs 6.
- Budget 9: cost 8, quality 175 (frontier-a diagnosis and low-b parsing).
- Budget 11: cost 11, quality 188 (frontier-b diagnosis and low-b parsing).

An explicit `min_cost` request chooses cost 6 and quality 160 when affordable.
Both objectives enforce the same layer and minimum-quality requirements.
