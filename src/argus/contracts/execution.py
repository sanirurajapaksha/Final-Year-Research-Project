"""M4's execution handler output: what happened when a command was (or wasn't) run."""

from pydantic import BaseModel


class ExecutionResult(BaseModel):
    command: str
    executed: bool
    output: str = ""
    error: str | None = None
