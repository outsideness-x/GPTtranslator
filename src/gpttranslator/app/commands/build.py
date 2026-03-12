"""Build command registration."""

from __future__ import annotations

import typer

from .common import emit_stub


def register(app: typer.Typer) -> None:
    """Register `build` command."""

    @app.command("build")
    def build_command() -> None:
        """Build output artifacts (stub)."""
        emit_stub("build")
