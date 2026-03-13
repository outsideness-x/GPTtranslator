"""Integration smoke test for full local pipeline in mock mode."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.cli import app

runner = CliRunner()


def test_full_pipeline_smoke_with_mock_backend_and_local_build() -> None:
    fixture_pdf = Path(__file__).resolve().parent / "fixtures" / "pdfs" / "text_fixture.pdf"
    assert fixture_pdf.exists()

    with runner.isolated_filesystem():
        source_pdf = Path("book.pdf")
        shutil.copy2(fixture_pdf, source_pdf)

        init_result = runner.invoke(app, ["init", str(source_pdf)])
        assert init_result.exit_code == 0

        workspace_root = Path("workspace")
        book_id = next(path.name for path in workspace_root.iterdir() if path.is_dir())
        book_root = workspace_root / book_id

        inspect_result = runner.invoke(app, ["inspect", book_id])
        assert inspect_result.exit_code == 0

        extract_result = runner.invoke(app, ["extract", book_id])
        assert extract_result.exit_code == 0

        glossary_result = runner.invoke(app, ["glossary", book_id])
        assert glossary_result.exit_code == 0

        translate_result = runner.invoke(
            app,
            [
                "translate",
                book_id,
                "--backend",
                "mock",
                "--profile",
                "balanced",
                "--batch-size",
                "2",
                "--strict-json",
            ],
        )
        assert translate_result.exit_code == 0

        qa_result = runner.invoke(app, ["qa", book_id, "--local-only"])
        assert qa_result.exit_code == 0

        build_result = runner.invoke(app, ["build", book_id])
        assert build_result.exit_code == 0

        status_result = runner.invoke(app, ["status", book_id])
        assert status_result.exit_code == 0
        assert "Book status" in status_result.output
        assert "translate" in status_result.output
        assert "build" in status_result.output

        assert (book_root / "output" / "qa_report.md").exists()
        assert (book_root / "output" / "build_report.md").exists()
        assert (book_root / "output" / "translation_summary.md").exists()
        assert (book_root / "output" / "translated_book.pdf").exists()
        assert (book_root / "logs" / "run.log").exists()
        assert (book_root / "logs" / "codex_jobs.jsonl").exists()
