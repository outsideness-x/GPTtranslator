"""Glossary command registration."""

from __future__ import annotations

import typer

from .common import emit_stub


def register(app: typer.Typer) -> None:
    """Register `glossary` command."""

    @app.command("glossary")
    def glossary_command() -> None:
        """Manage glossary entries (stub)."""
        emit_stub("glossary")
