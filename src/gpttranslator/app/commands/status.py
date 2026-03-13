"""Status command registration."""

from __future__ import annotations

import typer

from ..core.config import load_config
from ..core.paths import build_workspace_paths, resolve_workspace_root
from ..core.reporting import collect_book_run_summary, write_translation_summary
from ..core.state import load_workspace_state


def register(app: typer.Typer) -> None:
    """Register `status` command."""

    @app.command("status")
    def status_command(book_id: str | None = typer.Argument(None, help="Book ID from `gpttranslator init`.")) -> None:
        """Show workspace status or detailed per-book pipeline status."""
        config = load_config()
        workspace_root = resolve_workspace_root(config.project_root, config.workspace_dir_name)
        paths = build_workspace_paths(workspace_root, config.state_filename)

        if not paths.root.exists():
            typer.echo("Status: no active workspace. Project is not initialized.")
            return

        selected_book_id = book_id
        if selected_book_id is None:
            if not paths.state_path.exists():
                typer.echo("Status: no active workspace. Project is not initialized.")
                return
            state = load_workspace_state(paths.state_path)
            if not state.initialized or not state.active_book_id:
                typer.echo("Status: no active workspace. Project is not initialized.")
                return
            selected_book_id = state.active_book_id
            active_path = paths.root / selected_book_id
            typer.echo(f"Status: workspace initialized. Active book: {selected_book_id}")
            typer.echo(f"Path: {active_path}")
            return

        assert selected_book_id is not None
        book_root = paths.root / selected_book_id
        if not book_root.exists() or not book_root.is_dir():
            typer.secho(f"Status failed: book workspace not found: {selected_book_id}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        summary = collect_book_run_summary(book_root)
        summary_path = write_translation_summary(book_root, summary)

        typer.secho("Book status", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID              : {selected_book_id}")
        typer.echo(f"  Workspace            : {book_root}")
        typer.echo("  Stages:")
        for stage in ("init", "inspect", "extract", "translate", "qa", "build"):
            typer.echo(f"    {stage:<18} {summary.stage_statuses.get(stage, 'pending')}")
        typer.echo("  Summary:")
        typer.echo(f"    pages              : {summary.page_count}")
        typer.echo(f"    blocks             : {summary.block_count}")
        typer.echo(f"    chunks             : {summary.chunk_count}")
        typer.echo(f"    codex jobs         : {summary.codex_jobs_count}")
        typer.echo(f"    retries            : {summary.retries_count}")
        typer.echo(f"    qa flags           : {summary.qa_flags_count}")
        typer.echo(f"    pdf build status   : {summary.build_pdf_status}")
        typer.echo("  Artifacts:")
        typer.echo(f"    translation summary: {summary_path}")
        typer.echo(f"    qa report          : {book_root / 'output' / 'qa_report.md'}")
        typer.echo(f"    build report       : {book_root / 'output' / 'build_report.md'}")
        typer.echo(f"    run log            : {book_root / 'logs' / 'run.log'}")
        typer.echo(f"    codex jobs log     : {book_root / 'logs' / 'codex_jobs.jsonl'}")
