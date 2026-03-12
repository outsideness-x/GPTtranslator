"""Version command registration."""

from __future__ import annotations

import typer

from ... import __version__


def register(app: typer.Typer) -> None:
    """Register `version` command."""

    @app.command("version")
    def version_command() -> None:
        """Print CLI version."""
        typer.echo(f"GPTtranslator {__version__}")
