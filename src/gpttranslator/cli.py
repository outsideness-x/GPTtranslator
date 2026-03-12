"""CLI entrypoint for GPTtranslate."""

from __future__ import annotations

import typer
from rich.console import Console

from . import __version__

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


def _stub(command: str) -> None:
    typer.echo(f"[{command}] Stub command. Workflow implementation is not available in this stage.")


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """GPTtranslate terminal CLI."""
    if ctx.invoked_subcommand is None:
        _print_banner()
        typer.echo("Use `gpttranslator --help` to see available commands.")
        raise typer.Exit(code=0)


@app.command("help")
def help_command(ctx: typer.Context) -> None:
    """Show command help."""
    parent_ctx = ctx.parent if ctx.parent is not None else ctx
    typer.echo(parent_ctx.get_help())


@app.command("status")
def status_command() -> None:
    """Show current project status."""
    typer.echo("Status: no active workspace. Project is not initialized.")


@app.command("init")
def init_command() -> None:
    """Initialize GPTtranslate workspace (stub)."""
    _stub("init")


@app.command("inspect")
def inspect_command() -> None:
    """Inspect source materials (stub)."""
    _stub("inspect")


@app.command("extract")
def extract_command() -> None:
    """Extract translatable units (stub)."""
    _stub("extract")


@app.command("glossary")
def glossary_command() -> None:
    """Manage glossary entries (stub)."""
    _stub("glossary")


@app.command("translate")
def translate_command() -> None:
    """Run translation pipeline (stub)."""
    _stub("translate")


@app.command("qa")
def qa_command() -> None:
    """Run QA checks (stub)."""
    _stub("qa")


@app.command("build")
def build_command() -> None:
    """Build output artifacts (stub)."""
    _stub("build")


@app.command("version")
def version_command() -> None:
    """Print CLI version."""
    typer.echo(f"GPTtranslator {__version__}")


def main() -> None:
    """Run the CLI app."""
    app()


if __name__ == "__main__":
    main()
