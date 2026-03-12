"""QA command registration."""

from __future__ import annotations

import typer

from .common import emit_stub


def register(app: typer.Typer) -> None:
    """Register `qa` command."""

    @app.command("qa")
    def qa_command() -> None:
        """Run QA checks (stub)."""
        emit_stub("qa")
