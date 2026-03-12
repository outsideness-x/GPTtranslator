"""CLI tests for `gpttranslator glossary`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.cli import app

from _pdf_test_utils import write_simple_text_pdf

runner = CliRunner()


def test_glossary_command_creates_templates_and_prints_summary() -> None:
    with runner.isolated_filesystem():
        source_pdf = Path("book.pdf")
        write_simple_text_pdf(source_pdf)

        init_result = runner.invoke(app, ["init", str(source_pdf)])
        assert init_result.exit_code == 0

        workspace_root = Path("workspace")
        book_id = next(path.name for path in workspace_root.iterdir() if path.is_dir())
        memory_dir = workspace_root / book_id / "memory"

        for filename in ("glossary.md", "style_guide.md", "chapter_notes.md", "translation_memory.jsonl"):
            (memory_dir / filename).unlink()

        glossary_result = runner.invoke(app, ["glossary", book_id])
        assert glossary_result.exit_code == 0
        assert "Memory summary" in glossary_result.output
        assert "Templates created" in glossary_result.output

        glossary_text = (memory_dir / "glossary.md").read_text(encoding="utf-8")
        style_text = (memory_dir / "style_guide.md").read_text(encoding="utf-8")
        notes_text = (memory_dir / "chapter_notes.md").read_text(encoding="utf-8")
        tm_text = (memory_dir / "translation_memory.jsonl").read_text(encoding="utf-8")

        assert "# Glossary" in glossary_text
        assert "## Term Table" in glossary_text
        assert "# Style Guide" in style_text
        assert "# Chapter Notes" in notes_text
        assert tm_text == ""


def test_glossary_command_searches_glossary_and_tm() -> None:
    with runner.isolated_filesystem():
        source_pdf = Path("book.pdf")
        write_simple_text_pdf(source_pdf)

        init_result = runner.invoke(app, ["init", str(source_pdf)])
        assert init_result.exit_code == 0

        workspace_root = Path("workspace")
        book_id = next(path.name for path in workspace_root.iterdir() if path.is_dir())
        memory_dir = workspace_root / book_id / "memory"

        runner.invoke(app, ["glossary", book_id])

        glossary_path = memory_dir / "glossary.md"
        glossary_path.write_text(
            glossary_path.read_text(encoding="utf-8")
            + "| Algorithm | Алгоритм | noun | preferred | Keep singular form by default. |\n",
            encoding="utf-8",
        )

        tm_path = memory_dir / "translation_memory.jsonl"
        tm_path.write_text(
            json.dumps({"source_text": "algorithmic bias", "target_text": "algorithmic bias"})
            + "\n",
            encoding="utf-8",
        )

        glossary_result = runner.invoke(app, ["glossary", book_id, "--find", "algorithm"])
        assert glossary_result.exit_code == 0
        assert "Search query" in glossary_result.output
        assert "Glossary matches" in glossary_result.output
        assert "TM matches" in glossary_result.output


def test_glossary_command_fails_for_unknown_book() -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["glossary", "missing-book"])

    assert result.exit_code == 1
    assert "workspace not found" in result.output.lower()
