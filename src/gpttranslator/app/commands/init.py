"""Init command registration."""

from __future__ import annotations

from pathlib import Path

import typer

from ..core.config import load_config
from ..core.logging import get_logger
from ..core.manifest import save_book_manifest
from ..core.paths import build_workspace_paths, resolve_workspace_root
from ..core.state import touch_workspace_state
from ..pdf.ingestion import IngestionError, create_initial_manifest_payload, initialize_book_workspace


def register(app: typer.Typer) -> None:
    """Register `init` command."""

    @app.command("init")
    def init_command(pdf_path: Path = typer.Argument(..., help="Path to source PDF book.")) -> None:
        """Initialize a local book workspace from source PDF."""
        config = load_config()
        logger = get_logger("commands.init")

        try:
            result = initialize_book_workspace(
                pdf_path=pdf_path,
                project_root=config.project_root,
                workspace_dir_name=config.workspace_dir_name,
            )

            manifest = create_initial_manifest_payload(result)
            save_book_manifest(result.book_workspace.manifest_path, manifest)

            workspace_root = resolve_workspace_root(config.project_root, config.workspace_dir_name)
            workspace_paths = build_workspace_paths(workspace_root, config.state_filename)
            touch_workspace_state(
                workspace_paths.state_path,
                initialized=True,
                active_book_id=result.book_id,
            )
        except IngestionError as exc:
            typer.secho(f"Init failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        except ValueError as exc:
            typer.secho(f"Init failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        logger.info("book workspace initialized: %s", result.book_workspace.root)

        typer.secho("Workspace initialized", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID     : {result.book_id}")
        typer.echo(f"  Source PDF  : {result.source_pdf}")
        typer.echo(f"  Workspace   : {result.book_workspace.root}")
        typer.echo(f"  Copied PDF  : {result.book_workspace.original_pdf_path}")
        typer.echo(f"  Manifest    : {result.book_workspace.manifest_path}")
        typer.echo("  Memory seed : glossary.md, style_guide.md, chapter_notes.md, translation_memory.jsonl")
