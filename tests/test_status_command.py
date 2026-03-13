"""Tests for `gpttranslator status` detailed per-book output."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.core.manifest import save_book_manifest
from gpttranslator.app.core.models import BookManifest
from gpttranslator.cli import app

runner = CliRunner()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _prepare_workspace(root: Path, book_id: str) -> Path:
    book_root = root / "workspace" / book_id
    (book_root / "input").mkdir(parents=True, exist_ok=True)
    (book_root / "analysis").mkdir(parents=True, exist_ok=True)
    (book_root / "translated").mkdir(parents=True, exist_ok=True)
    (book_root / "output").mkdir(parents=True, exist_ok=True)
    (book_root / "logs").mkdir(parents=True, exist_ok=True)

    (book_root / "input" / "original.pdf").write_bytes(b"%PDF-1.4\n")
    (book_root / "analysis" / "inspection_report.json").write_text("{}", encoding="utf-8")
    (book_root / "analysis" / "document_graph.json").write_text("{}", encoding="utf-8")

    _write_jsonl(book_root / "analysis" / "pages.jsonl", [{"page_num": 1}, {"page_num": 2}, {"page_num": 3}])
    _write_jsonl(
        book_root / "analysis" / "blocks.jsonl",
        [{"block_id": "b1"}, {"block_id": "b2"}, {"block_id": "b3"}, {"block_id": "b4"}, {"block_id": "b5"}],
    )
    _write_jsonl(
        book_root / "analysis" / "chunks.jsonl",
        [
            {"chunk_id": "c1", "status": "completed"},
            {"chunk_id": "c2", "status": "completed"},
            {"chunk_id": "c3", "status": "completed"},
            {"chunk_id": "c4", "status": "completed"},
        ],
    )
    _write_jsonl(book_root / "translated" / "translated_chunks.jsonl", [{"chunk_id": "c1", "status": "completed"}])
    _write_jsonl(book_root / "translated" / "qa_flags.jsonl", [{"chunk_id": "c1"}, {"chunk_id": "c2"}])
    _write_jsonl(
        book_root / "logs" / "codex_jobs.jsonl",
        [
            {"job_id": "j1", "attempt_count": 1},
            {"job_id": "j2", "attempt_count": 2},
        ],
    )
    (book_root / "output" / "qa_report.md").write_text("# QA report\n", encoding="utf-8")
    (book_root / "output" / "build_report.md").write_text("# Build report\n", encoding="utf-8")
    (book_root / "output" / "translated_book.pdf").write_bytes(b"%PDF-1.4\n")

    manifest = BookManifest(
        book_id=book_id,
        source_pdf="input/original.pdf",
        metadata={
            "pipeline": {
                "inspect": "done",
                "extract": "done",
                "translate": "done",
                "qa": "done",
                "build": "done",
            }
        },
    )
    save_book_manifest(book_root / "manifest.json", manifest)
    return book_root


def test_status_command_with_book_id_prints_stage_statuses_and_summary() -> None:
    with runner.isolated_filesystem():
        root = Path(".")
        book_id = "book-status"
        book_root = _prepare_workspace(root, book_id)

        result = runner.invoke(app, ["status", book_id])
        assert result.exit_code == 0
        assert "Book status" in result.output
        assert "init" in result.output
        assert "inspect" in result.output
        assert "extract" in result.output
        assert "translate" in result.output
        assert "qa" in result.output
        assert "build" in result.output
        assert "pages              : 3" in result.output
        assert "blocks             : 5" in result.output
        assert "chunks             : 4" in result.output
        assert "codex jobs         : 2" in result.output
        assert "retries            : 1" in result.output
        assert "qa flags           : 2" in result.output
        assert "pdf build status   : built" in result.output

        summary_path = book_root / "output" / "translation_summary.md"
        assert summary_path.exists()
        summary_text = summary_path.read_text(encoding="utf-8")
        assert "Codex jobs: **2**" in summary_text
        assert "Retries: **1**" in summary_text


def test_status_command_fails_for_missing_book_id() -> None:
    with runner.isolated_filesystem():
        Path("workspace").mkdir(parents=True, exist_ok=True)
        result = runner.invoke(app, ["status", "missing-book"])
    assert result.exit_code == 1
    assert "status failed" in result.output.lower()
