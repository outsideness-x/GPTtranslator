"""Translate command registration."""

from __future__ import annotations

import typer

from .common import emit_stub


def register(app: typer.Typer) -> None:
    """Register `translate` command."""

    @app.command("translate")
    def translate_command() -> None:
        """Run translation pipeline (stub)."""
        emit_stub("translate")
