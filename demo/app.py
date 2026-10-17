"""Compatibility entry point for existing Streamlit commands and sessions."""

import runpy

runpy.run_module("argus.orchestration.dashboard.app", run_name="__main__")
