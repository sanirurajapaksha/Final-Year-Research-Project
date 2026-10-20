"""Settings and small helpers shared by the demo's page (app.py) and command line (__main__.py).

The incident run itself is in flow.py.
"""

from dataclasses import replace
from pathlib import Path

from argus.config import Settings, load_settings

REPO = Path(__file__).resolve().parents[3]
KUBECTL_OUTPUT = REPO / "data" / "fixtures" / "m3" / "kubectl"
DEMO_MODEL = "google/gemini-2.5-flash-lite"  # development and demo model (decided 17/10)


def demo_settings() -> Settings:
    """The user's settings, with the demo's defaults where nothing is set."""
    settings = load_settings()
    if not settings.m3_kubectl_output:
        settings = replace(settings, m3_kubectl_output=str(KUBECTL_OUTPUT))
    if not settings.llm_model:
        settings = replace(settings, llm_model=DEMO_MODEL)
    return settings


def verdict_line(verdict: dict) -> str:
    """'M3: BLOCK (z3: sat)'; without the z3 part when M3 decided before the solver ran."""
    text = f"M3: {verdict['decision']}"
    if verdict["z3_result"] is not None:
        text += f" (z3: {verdict['z3_result']})"
    return text
