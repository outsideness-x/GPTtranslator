"""Configuration primitives for GPTtranslate."""

from __future__ import annotations

import os
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

    root_override = project_root or _env_path("GPTTRANSLATOR_PROJECT_ROOT")
    root = (root_override or Path.cwd()).resolve()
    return AppConfig(
        app_name="GPTtranslate",
        version=__version__,
        project_root=root,
        workspace_dir_name="workspace",
        manifest_filename="manifest.json",
        state_filename="state.json",
        log_level=os.environ.get("GPTTRANSLATOR_LOG_LEVEL", "INFO"),
        codex_command=os.environ.get("GPTTRANSLATOR_CODEX_COMMAND", "codex"),
        default_profile="balanced",
        very_long_book_page_threshold=450,
        default_max_context_entries=12,
        default_max_retries=2,
        default_tm_first=True,
        default_reuse_cache=True,
        default_adaptive_chunking=True,
        default_qa_on_risk_only=True,
    )


def _env_path(name: str) -> Path | None:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        return None
    return Path(value)
