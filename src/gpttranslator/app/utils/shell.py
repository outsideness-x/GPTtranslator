"""Shell execution utility abstractions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ShellCommandResult:
    """Normalized shell command result."""

    return_code: int
    stdout: str
    stderr: str


def not_implemented_shellout(command: str) -> ShellCommandResult:
    """Stub for future shell-out orchestration."""

    return ShellCommandResult(
        return_code=1,
        stdout="",
        stderr=f"Shell-out is not implemented yet: {command}",
    )
