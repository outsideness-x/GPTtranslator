"""Help command registration."""

from __future__ import annotations

import typer


def register(app: typer.Typer) -> None:
    """Register `help` command."""

    @app.command("help")
    def help_command(ctx: typer.Context) -> None:
        """Show command help."""
        parent_ctx = ctx.parent if ctx.parent is not None else ctx
        typer.echo(parent_ctx.get_help())
