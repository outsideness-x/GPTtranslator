"""Main Typer application wiring."""

from __future__ import annotations

import typer
from rich.console import Console

from .commands.registry import register_commands
from .core.config import load_config
from .core.logging import configure_logging

console = Console()

BANNER_LINES: tuple[str, ...] = (
    "  ____ ____ _____ _____                         _       _",
    " / ___|  _ \\_   _|_   _| __ __ _ _ __  ___  ___| | __ _| |_ ___  _ __",
    "| |  _| |_) || |   | || '__/ _` | '_ \\/ __|/ _ \\ |/ _` | __/ _ \\| '__|",
    "| |_| |  __/ | |   | || | | (_| | | | \\__ \\  __/ | (_| | || (_) | |",
    " \\____|_|    |_|   |_||_|  \\__,_|_| |_|___/\\___|_|\\__,_|\\__\\___/|_|",
)
BANNER_STYLES: tuple[str, ...] = ("cyan", "bright_cyan", "blue", "bright_blue", "cyan")

app = typer.Typer(
    name="gpttranslator",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
    help="Minimalist CLI shell for GPTtranslate.",
    epilog="Run `gpttranslator help` or `gpttranslator --help` for command reference.",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _print_banner() -> None:
    for line, style in zip(BANNER_LINES, BANNER_STYLES, strict=True):
        console.print(line, style=style)
    typer.echo()
    typer.echo("GPTtranslate CLI shell")


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """GPTtranslate terminal CLI."""
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
