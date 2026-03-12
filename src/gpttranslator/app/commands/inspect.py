"""Inspect command registration."""

from __future__ import annotations

import typer

from .common import emit_stub


def register(app: typer.Typer) -> None:
    """Register `inspect` command."""

    @app.command("inspect")
    def inspect_command() -> None:
        """Inspect source materials (stub)."""
        emit_stub("inspect")
