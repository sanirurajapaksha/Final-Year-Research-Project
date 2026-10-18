# Local M4 dashboard

Run these commands from the repository root (Python 3.12+):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[demo,dev]"
.\.venv\Scripts\python.exe -m argus.orchestration.dashboard
```

Open http://localhost:8501. Stop with Ctrl+C. No database or hosted service is needed.
The previous `python -m streamlit run demo/app.py` command also works through a
compatibility entry point; the dashboard implementation lives in the installed package.
The optional demo dependency does not change the core application's dependencies.

Select the synthetic scenario_01 fixture or upload a contract v1 TelemetryBatch JSON.
Explore searchable Metrics, Logs, Spans and Kubernetes tables, compare both JSON baselines,
and download the original JSON, raw TSV or measurement summary. Invalid input shows an error.
Tables format nested values for readability; measurements use the actual UTF-8 payloads.
The compact JSON baseline is primary; default JSON is reported separately.
These are byte measurements for the selected input, not token savings or aggregate research results.

Use **Demo section** in the sidebar to switch between:

- **Telemetry Compression**: existing M4 compression and M1 validation/decoding.
- **Routing & Budget**: the existing offline router chooses models for two synthetic
  tasks. Adjust shared budget, minimum quality and the optimization objective.
  The candidate table explains layer and quality eligibility. Download the inputs
  and computed plan as JSON. Credits and quality scores are invented estimates.
- **Fallback & Safety**: run an independent scripted diagnostic scenario through
  `run_function2()`. Choose success, timeout, invalid output or model error, and
  inspect the ordered attempts, estimated spending and validated diagnosis.
  The primary costs 2 credits and the fallback costs 3: budget 5 permits recovery,
  budget 4 stops the fallback and budget below 2 starts no calls.
  Proposing 1 geo replica demonstrates BLOCK and counterexample feedback;
  proposing 2 demonstrates APPROVE against the hand-written M3 snapshot.
  The actual M3 gate runs locally; every executor result has `executed=False`.
  The feedback callback returns a scripted revised proposal that is retained
  without execution. Download the full scenario, policy, snapshot and results.

The F2 scenario is separate from the telemetry input; it does not diagnose an upload
or implement M2's reasoning. Changing its controls hides prior results until Run
is pressed again. The dashboard makes no real provider calls, executes no cluster
commands and does not modify saved experiment evidence. Timeouts are simulated;
budget figures are estimated credits rather than billed usage. Routing controls
are local prototype policies, not claims of team-approved provider configuration.

For a short terminal summary using the same measurement function:

```powershell
.\.venv\Scripts\python.exe -m argus.orchestration.dashboard.check_output
# Optional custom fixture:
.\.venv\Scripts\python.exe -m argus.orchestration.dashboard.check_output path/to/telemetry.json
```

Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/demo -v
```

The Streamlit interaction test is skipped when the optional dependency is not installed.
