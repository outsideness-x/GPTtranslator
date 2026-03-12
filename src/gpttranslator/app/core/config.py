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
    default_profile: str
    very_long_book_page_threshold: int
    default_max_context_entries: int
    default_max_retries: int
    default_tm_first: bool
    default_reuse_cache: bool
    default_adaptive_chunking: bool
    default_qa_on_risk_only: bool


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
        default_profile="balanced",
        very_long_book_page_threshold=450,
        default_max_context_entries=12,
        default_max_retries=2,
        default_tm_first=True,
        default_reuse_cache=True,
        default_adaptive_chunking=True,
        default_qa_on_risk_only=True,
    )
