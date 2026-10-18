# Argus

**Argus** is the AI SRE agent built for the SLIIT IT4010 research project **"Multi-Benchmark Investigation and Development of Enhanced Autonomous AI SRE Agents"** (group J26-SE-305). This repository (`Final-Year-Research-Project`) holds all of its code.

> **Status:** boilerplate. The folders, shared contracts, a stub pipeline, tests and CI are in place. Every module is a stub that its owner replaces. Nothing here touches a real cluster yet.

## The system in one paragraph
Argus diagnoses and fixes incidents in a Kubernetes cluster. It is one Python application with four modules. Telemetry enters through **M4** (orchestration), which compresses it for **M1** (context). M1 builds a structured picture of the incident, and **M2** (diagnosis) ranks root-cause hypotheses and proposes actions. Read actions run freely; every write action must pass **M3** (safety gate) before M4 executes it. Details: [docs/architecture.md](docs/architecture.md).

| Module | Folder | Owner |
|---|---|---|
| M1 System Context Acquisition & Observation Layer | `src/argus/context/` | Minidu Weerasinghe |
| M2 Multi-Hypothesis Diagnostic RCA | `src/argus/diagnosis/` | Kaveen Pasindumal |
| M3 Proactive Formal Verification Safety Layer | `src/argus/safety/` | Saniru Rajapaksha |
| M4 Adaptive Tool Orchestration & Token Manager | `src/argus/orchestration/` | Nethmi Herath |

## If you know a MERN boilerplate

| In a MERN app | Here | Why |
|---|---|---|
| `models/` (Mongoose schemas) | `src/argus/contracts/` (Pydantic models) | The shape data must have when it crosses a module boundary |
| `routes/` + `controllers/` | `src/argus/orchestration/pipeline.py` | Decides which module handles what, in what order |
| `services/` | `context/`, `diagnosis/`, `safety/`, `orchestration/` | The real work, one package per module |
| `middleware/` (e.g. auth) | `safety/` (M3 gate) | Every write passes through it before it reaches the cluster, like auth before a protected route |
| `config/` + `.env` | `src/argus/config.py` + `.env.example` | Settings and secrets |
| `package.json` scripts | `pyproject.toml` + the commands below | Dependencies and how to run things |
| The database | The Kubernetes cluster and its telemetry | What the system reads and changes |
| `client/` (React) | none yet | No UI planned so far |

## Layout
```
.
├── src/argus/
│   ├── contracts/        shared typed messages between modules (draft v0)
│   ├── orchestration/    M4: preprocessing, routing, execution handler, pipeline wiring
│   ├── context/          M1
│   ├── diagnosis/        M2
│   ├── safety/           M3: prefilter → extractor → formulation → compiler → sandbox → gate
│   ├── integrations/     shared adapters (benchmark, Kubernetes clients), not built yet
│   ├── llm/              shared LLM access, not built yet
│   ├── common/           logging and per-stage timing
│   ├── config.py         settings from environment variables
│   └── __main__.py       demo: `python -m argus`
├── tests/
│   ├── unit/<module>/    each owner's unit tests
│   └── integration/      cross-module tests (e.g. "no write runs without M3's approval")
├── data/                 fixtures/ (small test inputs), corpora/ (labelled datasets)
├── experiments/          dated runs with raw results (research evidence)
├── docs/                 architecture, contracts, function specs
├── scripts/              dev helpers (cluster set-up etc.)
└── .github/              CI and the PR template
```

## Getting started
Requires Python 3.12 or newer.

```bash
python -m venv .venv
```

Activate the environment (`source .venv/bin/activate` on Linux/macOS, `.venv\Scripts\activate` on Windows), then:

```bash
pip install -e ".[dev]"
```

```bash
pytest
```

```bash
ruff check . && ruff format --check .
```

```bash
python -m argus
```

The last command runs one pass of the stub pipeline on `data/fixtures/telemetry_sample.json`. With the stubs in place, M3 blocks the sample write command (fail-closed) and nothing is executed.

Copy `.env.example` to `.env` for local settings. `.env` is git-ignored.

## Working together

For live M4 compression measurements, readable telemetry tables, interactive offline
model routing, and scripted fallback/safety scenarios, see
[the optional local dashboard](src/argus/orchestration/dashboard/README.md).
It also provides a short terminal compression summary command.
See [CONTRIBUTING.md](CONTRIBUTING.md): feature branches and PRs, tests for every function, module ownership, no secrets, and cluster safety.

## Not decided yet
The orchestration framework (CrewAI or LangGraph), the LLM provider and contract v1 are still open; see [docs/architecture.md](docs/architecture.md#still-open). The structure is a starting point: change it when the work needs something better.
