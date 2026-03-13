"""Packaging metadata tests for installability guarantees."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_declares_console_script_and_prompt_assets() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert payload["project"]["scripts"]["gpttranslator"] == "gpttranslator.cli:main"
    assert payload["tool"]["setuptools"]["package-data"]["gpttranslator.prompt_assets"] == ["*.md", "*.txt"]


def test_bundled_prompt_assets_match_repository_prompts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_dir = repo_root / "prompts"
    bundled_dir = repo_root / "src" / "gpttranslator" / "prompt_assets"

    filenames = {
        "README.md",
        "chapter_summary.prompt.md",
        "editorial_pass.prompt.md",
        "glossary_update_proposal.prompt.md",
        "semantic_qa.prompt.md",
        "terminology_check.prompt.md",
        "translate_chunk.prompt.md",
        "translate_system.prompt.txt",
    }

    for filename in filenames:
        assert (bundled_dir / filename).read_text(encoding="utf-8") == (source_dir / filename).read_text(
            encoding="utf-8"
        )
