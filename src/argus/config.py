"""Runtime settings. Defaults live here; override them with environment variables (see .env.example).

The command-line entry points load the git-ignored .env file into the environment first
(python-dotenv); this module itself only reads the environment, so tests stay independent of .env.

Secrets such as API keys are deliberately not stored on Settings, so they can't leak into logs.
The code that needs a key reads it from the environment itself.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    log_level: str = "INFO"
    llm_model: str = ""
    # Context name of the disposable dev cluster; empty means no cluster is configured.
    kube_context: str = ""
    # M3 sandbox limits (placeholders until measured). The memory cap limits address space (RLIMIT_AS);
    # 256 MB made every solver call fail with MemoryError on Fedora (PR #14 review), 512 MB works.
    solver_timeout_s: float = 5.0
    solver_memory_mb: int = 512
    # Folder of saved `kubectl get -o json` output that M3's extractor reads instead of a cluster
    # (PP1 has no cluster). Empty: M3 reads the live cluster in kube_context, if one is set.
    m3_kubectl_output: str = ""
    # JSONL file where M3's Formulation Agent appends every raw LLM answer (scratch/ is git-ignored).
    m3_llm_log: str = "scratch/m3_llm_outputs.jsonl"
    # M2 uses the LLM only when this is on. The key and model above are shared with M3, so having them
    # set must not make every M2 run paid and non-repeatable; off means M2 runs on its rules.
    m2_use_llm: bool = False


def load_settings() -> Settings:
    return Settings(
        log_level=os.environ.get("ARGUS_LOG_LEVEL", Settings.log_level),
        llm_model=os.environ.get("ARGUS_LLM_MODEL", Settings.llm_model),
        kube_context=os.environ.get("ARGUS_KUBE_CONTEXT", Settings.kube_context),
        solver_timeout_s=float(os.environ.get("ARGUS_SOLVER_TIMEOUT_S", Settings.solver_timeout_s)),
        solver_memory_mb=int(os.environ.get("ARGUS_SOLVER_MEMORY_MB", Settings.solver_memory_mb)),
        m3_kubectl_output=os.environ.get("ARGUS_M3_KUBECTL_OUTPUT", Settings.m3_kubectl_output),
        m3_llm_log=os.environ.get("ARGUS_M3_LLM_LOG", Settings.m3_llm_log),
        m2_use_llm=os.environ.get("ARGUS_M2_USE_LLM", "").strip().lower() in ("1", "true", "yes", "on"),
    )
