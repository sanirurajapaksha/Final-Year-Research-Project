# M2: Multi-Hypothesis Diagnostic RCA

**Owner:** Kaveen Pasindumal

**Role in the flow:** Semantic Context Object (via M4) → **M2** → hypotheses + proposed actions. Read actions run freely; each write action goes M2 → M4 → M3. M3's BLOCK verdicts (with counterexamples) come back to M2 as `feedback`.

**Entry point:** `service.diagnose(SemanticContext, feedback) -> DiagnosisResult` (stub for now).

**Planned work** (from the proposal and the PP1 plan; yours to confirm or replace):
- Function 1: hypothesis generation and a belief-state tracker, producing ranked root-cause hypotheses with probabilities.
- Function 2: tree search and a read/write splitter. Reads are the next diagnostic steps; writes are routed to M4 → M3.
- Metrics: diagnostic F1, mean time to correct diagnosis, mitigation accuracy.

**One rule that affects everyone:** `ProposedAction.command` must be the exact string that will run. M3 checks that string, so nothing downstream may rewrite it.

**Internal layout:** up to you. Put tests in `tests/unit/diagnosis/`.
