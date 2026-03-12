"""Integration-like tests for `gpttranslator translate` command."""

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


def _prepare_book_workspace(root: Path, book_id: str) -> Path:
    book_root = root / "workspace" / book_id
    (book_root / "analysis").mkdir(parents=True, exist_ok=True)
    (book_root / "memory").mkdir(parents=True, exist_ok=True)
    (book_root / "translated").mkdir(parents=True, exist_ok=True)
    (book_root / "logs").mkdir(parents=True, exist_ok=True)
    (book_root / "input").mkdir(parents=True, exist_ok=True)

    manifest = BookManifest(
        book_id=book_id,
        source_pdf="input/original.pdf",
        metadata={"extraction": {"page_count": 2}},
    )
    save_book_manifest(book_root / "manifest.json", manifest)

    chunks = [
        {
            "chunk_id": "chunk-1",
            "chapter_id": "chapter-01",
            "page_range": [1, 1],
            "block_ids": ["b1"],
            "chunk_type": "paragraph_group",
            "source_text": "First sentence for translation [1].",
            "local_context_before": "",
            "local_context_after": "",
            "footnote_refs": [{"marker": "[1]"}],
            "glossary_hints": [],
            "metadata": {},
        },
        {
            "chunk_id": "chunk-2",
            "chapter_id": "chapter-01",
            "page_range": [1, 2],
            "block_ids": ["b2"],
            "chunk_type": "paragraph_group",
            "source_text": "Second sentence for translation.",
            "local_context_before": "",
            "local_context_after": "",
            "footnote_refs": [],
            "glossary_hints": [],
            "metadata": {},
        },
    ]
    chunks_path = book_root / "analysis" / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as file:
        for item in chunks:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")

    (book_root / "memory" / "glossary.md").write_text(
        "# Glossary\n\n## Term Table\n| Source term | Target term | POS | Decision | Notes |\n|---|---|---|---|---|\n| sentence | предложение | noun | preferred | |\n",
        encoding="utf-8",
    )
    (book_root / "memory" / "style_guide.md").write_text(
        "# Style Guide\n- Keep formal register.\n",
        encoding="utf-8",
    )
    (book_root / "memory" / "chapter_notes.md").write_text(
        "# Chapter Notes\n\n## Global Notes\n- Preserve footnote markers.\n\n## chapter-01\n- Stay consistent.\n",
        encoding="utf-8",
    )
    (book_root / "memory" / "translation_memory.jsonl").write_text("", encoding="utf-8")
    return book_root


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def test_translate_runs_chunk_batch_pipeline_and_writes_logs() -> None:
    with runner.isolated_filesystem():
        root = Path(".")
        book_id = "book-translate"
        book_root = _prepare_book_workspace(root, book_id)

        result = runner.invoke(
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

        assert result.exit_code == 0
        assert "Batch execution completed" in result.output
        assert "Progress" in result.output
        assert "Editorial pass completed" in result.output
        assert "Consistency pass completed" in result.output

        translated_chunks = _read_jsonl(book_root / "translated" / "translated_chunks.jsonl")
        edited_chunks = _read_jsonl(book_root / "translated" / "edited_chunks.jsonl")
        consistency_flags_path = book_root / "translated" / "consistency_flags.jsonl"
        codex_jobs = _read_jsonl(book_root / "logs" / "codex_jobs.jsonl")
        codex_failures_path = book_root / "logs" / "codex_failures.jsonl"

        assert len(translated_chunks) == 2
        assert all(row.get("status") == "completed" for row in translated_chunks)
        assert len(edited_chunks) == 2
        assert len(codex_jobs) >= 4
        assert codex_failures_path.exists()
        assert consistency_flags_path.exists()
        assert codex_failures_path.read_text(encoding="utf-8").strip() == ""

        assert (book_root / "translated" / "batch_manifest.json").exists()
        assert (book_root / "translated" / "chunk_checkpoints.json").exists()


def test_translate_resume_skips_completed_chunks() -> None:
    with runner.isolated_filesystem():
        root = Path(".")
        book_id = "book-resume"
        book_root = _prepare_book_workspace(root, book_id)

        first = runner.invoke(
            app,
            [
                "translate",
                book_id,
                "--backend",
                "mock",
                "--batch-size",
                "1",
            ],
        )
        assert first.exit_code == 0

        translated_path = book_root / "translated" / "translated_chunks.jsonl"
        first_count = len(_read_jsonl(translated_path))
        assert first_count == 2

        second = runner.invoke(
            app,
            [
                "translate",
                book_id,
                "--backend",
                "mock",
                "--resume",
                "--batch-size",
                "1",
            ],
        )
        assert second.exit_code == 0

        second_count = len(_read_jsonl(translated_path))
        assert second_count == first_count

        edited_path = book_root / "translated" / "edited_chunks.jsonl"
        edited_count = len(_read_jsonl(edited_path))
        assert edited_count == 2
