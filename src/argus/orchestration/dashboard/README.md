# Local telemetry dashboard

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

The demo calls existing M4 compression and M1 validation/decoding functions. It does not
execute cluster commands, call a model, or modify saved experiment evidence.

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
