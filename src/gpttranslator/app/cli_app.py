"""Main Typer application wiring."""

from __future__ import annotations

import typer
from rich.console import Console

from .commands.registry import register_commands
from .core.config import load_config
from .core.logging import configure_logging

console = Console()

BANNER_LINES: tuple[str, ...] = (
    "░█▀▀░█▀█░▀█▀░░▀█▀░█▀▄░█▀█░█▀█░█▀▀░█░░░█▀█░▀█▀░█▀█░█▀▄",
    "░█░█░█▀▀░░█░░░░█░░█▀▄░█▀█░█░█░▀▀█░█░░░█▀█░░█░░█░█░█▀▄",
    "░▀▀▀░▀░░░░▀░░░░▀░░▀░▀░▀░▀░▀░▀░▀▀▀░▀▀▀░▀░▀░░▀░░▀▀▀░▀░▀",
)
BANNER_STYLES: tuple[str, ...] = ("cyan", "bright_cyan", "blue")

app = typer.Typer(
    name="gpttranslator",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
    help="Minimalist CLI shell for GPTtranslator.",
    epilog="Run `gpttranslator help` or `gpttranslator --help` for command reference.",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _print_banner() -> None:
    for line, style in zip(BANNER_LINES, BANNER_STYLES, strict=True):
        console.print(line, style=style)
    typer.echo()
    typer.echo("GPTtranslator CLI shell")


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """GPTtranslator terminal CLI."""
    config = load_config()
    configure_logging(config.log_level)

    if ctx.invoked_subcommand is None:
        _print_banner()
        typer.echo("Use `gpttranslator --help` to see available commands.")
        raise typer.Exit(code=0)


register_commands(app)


def main() -> None:
    """Run the CLI app."""
    app()


if __name__ == "__main__":
    main()
