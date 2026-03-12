"""Integration-like tests for `gpttranslator init`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.cli import app

runner = CliRunner()


def _write_valid_pdf(path: Path) -> None:
    path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n")


def test_init_creates_book_workspace_with_manifest_and_memory_files() -> None:
    with runner.isolated_filesystem():
        source_pdf = Path("book.pdf")
        _write_valid_pdf(source_pdf)

        result = runner.invoke(app, ["init", str(source_pdf)])
        assert result.exit_code == 0
        assert "Workspace initialized" in result.output

        workspace_root = Path("workspace")
        assert workspace_root.exists()

        book_dirs = [item for item in workspace_root.iterdir() if item.is_dir()]
        assert len(book_dirs) == 1

        book_root = book_dirs[0]
        assert (book_root / "input" / "original.pdf").exists()
        assert (book_root / "analysis").is_dir()
        assert (book_root / "memory").is_dir()
        assert (book_root / "translated").is_dir()
        assert (book_root / "output").is_dir()
        assert (book_root / "logs").is_dir()

        assert (book_root / "memory" / "glossary.md").exists()
        assert (book_root / "memory" / "style_guide.md").exists()
        assert (book_root / "memory" / "chapter_notes.md").exists()
        assert (book_root / "memory" / "translation_memory.jsonl").exists()

        assert (book_root / "memory" / "glossary.md").read_text(encoding="utf-8") == ""
        assert (book_root / "memory" / "style_guide.md").read_text(encoding="utf-8") == ""
        assert (book_root / "memory" / "chapter_notes.md").read_text(encoding="utf-8") == ""
        assert (book_root / "memory" / "translation_memory.jsonl").read_text(encoding="utf-8") == ""

        copied_pdf = (book_root / "input" / "original.pdf").read_bytes()
        assert copied_pdf == source_pdf.read_bytes()

        manifest_path = book_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["book_id"] == book_root.name
        assert manifest["source_pdf"] == "input/original.pdf"
        assert manifest["metadata"]["stage"] == "initialized"
        assert manifest["metadata"]["pipeline"]["translate"] == "pending"

        state = json.loads((workspace_root / "state.json").read_text(encoding="utf-8"))
        assert state["initialized"] is True
        assert state["active_book_id"] == book_root.name


def test_init_fails_when_pdf_file_missing() -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["init", "missing.pdf"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_init_fails_on_non_pdf_extension() -> None:
    with runner.isolated_filesystem():
        source_file = Path("book.txt")
        _write_valid_pdf(source_file)

        result = runner.invoke(app, ["init", str(source_file)])

    assert result.exit_code == 1
    assert ".pdf extension" in result.output.lower()


def test_init_fails_on_invalid_pdf_signature() -> None:
    with runner.isolated_filesystem():
        source_pdf = Path("broken.pdf")
        source_pdf.write_bytes(b"not-a-pdf")

        result = runner.invoke(app, ["init", str(source_pdf)])

    assert result.exit_code == 1
    assert "invalid pdf signature" in result.output.lower()
