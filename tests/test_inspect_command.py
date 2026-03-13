"""CLI tests for `gpttranslator inspect`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _pdf_test_utils import write_corrupted_pdf_with_signature, write_simple_text_pdf

from gpttranslator.cli import app

runner = CliRunner()


def test_inspect_command_creates_report_and_updates_manifest() -> None:
    with runner.isolated_filesystem():
        source_pdf = Path("book.pdf")
        write_simple_text_pdf(source_pdf)

        init_result = runner.invoke(app, ["init", str(source_pdf)])
        assert init_result.exit_code == 0

        workspace_root = Path("workspace")
        book_id = next(path.name for path in workspace_root.iterdir() if path.is_dir())

        inspect_result = runner.invoke(app, ["inspect", book_id])
        assert inspect_result.exit_code == 0
        assert "Inspection completed" in inspect_result.output
        assert "Text layer" in inspect_result.output

        report_path = workspace_root / book_id / "analysis" / "inspection_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["page_count"] == 2
        assert report["has_text_layer"] is True

        manifest_path = workspace_root / book_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["metadata"]["pipeline"]["inspect"] == "done"
        assert manifest["metadata"]["inspection"]["page_count"] == 2


def test_inspect_command_fails_for_unknown_book_id() -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["inspect", "missing-book"])

    assert result.exit_code == 1
    assert "workspace not found" in result.output.lower()


def test_inspect_command_handles_broken_pdf() -> None:
    with runner.isolated_filesystem():
        source_pdf = Path("broken.pdf")
        write_corrupted_pdf_with_signature(source_pdf)

        init_result = runner.invoke(app, ["init", str(source_pdf)])
        assert init_result.exit_code == 0

        workspace_root = Path("workspace")
        book_id = next(path.name for path in workspace_root.iterdir() if path.is_dir())

        inspect_result = runner.invoke(app, ["inspect", book_id])
        assert inspect_result.exit_code == 1
        assert "inspect failed" in inspect_result.output.lower()
