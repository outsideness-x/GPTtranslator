"""Extract command registration."""

from __future__ import annotations

import typer

from .common import emit_stub


def register(app: typer.Typer) -> None:
    """Register `extract` command."""

    @app.command("extract")
    def extract_command() -> None:
        """Extract translatable units (stub)."""
        emit_stub("extract")
