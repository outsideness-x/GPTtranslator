"""Status command registration."""

from __future__ import annotations

import typer

from ..core.config import load_config
from ..core.paths import build_workspace_paths, resolve_workspace_root
from ..core.state import load_workspace_state


def register(app: typer.Typer) -> None:
    """Register `status` command."""

    @app.command("status")
    def status_command() -> None:
        """Show current project status."""
        config = load_config()
        workspace_root = resolve_workspace_root(config.project_root, config.workspace_dir_name)
        paths = build_workspace_paths(workspace_root, config.state_filename)

        if not paths.root.exists() or not paths.state_path.exists():
            typer.echo("Status: no active workspace. Project is not initialized.")
            return

        state = load_workspace_state(paths.state_path)
        if not state.initialized or not state.active_book_id:
            typer.echo("Status: no active workspace. Project is not initialized.")
            return

        active_path = paths.root / state.active_book_id
        typer.echo(f"Status: workspace initialized. Active book: {state.active_book_id}")
        typer.echo(f"Path: {active_path}")
