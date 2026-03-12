"""Configuration primitives for GPTtranslate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ... import __version__


@dataclass(frozen=True)
class AppConfig:
    """Static application configuration for CLI runtime."""

    app_name: str
    version: str
    project_root: Path
    workspace_dir_name: str
    manifest_filename: str
    state_filename: str
    log_level: str
    codex_command: str


def load_config(project_root: Path | None = None) -> AppConfig:
    """Load default project configuration.

    This stage intentionally keeps configuration static and file-based.
    """

    root = (project_root or Path.cwd()).resolve()
    return AppConfig(
        app_name="GPTtranslate",
        version=__version__,
        project_root=root,
        workspace_dir_name="workspace",
        manifest_filename="book_manifest.json",
        state_filename="state.json",
        log_level="INFO",
        codex_command="codex",
    )
