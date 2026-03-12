"""Shared helpers for CLI commands."""

from __future__ import annotations

import typer


def emit_stub(command: str, details: str | None = None) -> None:
    """Emit a standardized message for not-yet-implemented commands."""

    message = f"[{command}] Stub command. Workflow implementation is not available in this stage."
    if details:
        message = f"{message} {details}"
    typer.echo(message)
