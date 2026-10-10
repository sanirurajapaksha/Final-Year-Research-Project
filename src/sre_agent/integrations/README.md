# Integrations (shared)

Adapters that talk to systems outside our code, so the modules don't each write their own.

Planned (nothing here yet):
- **Benchmark adapter:** how the agent receives a problem and its telemetry, and submits results. SREGym is the primary benchmark.
- **Kubernetes clients:** one read-only client (get, list, watch) for M1, M2 and M3's extractor, and one write client used only by M4's execution handler.

Rules: writes go through M4's execution handler only, after M3 approves them. Any code that touches a cluster checks the kube context first.
