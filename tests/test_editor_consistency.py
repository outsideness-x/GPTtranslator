"""Tests for editorial and consistency passes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.translation.codex_backend import MockCodexBackend
from gpttranslator.app.translation.consistency import ConsistencyOptions, run_consistency_pass
from gpttranslator.app.translation.editor import EditorialOptions, run_editorial_pass


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_editorial_pass_creates_edited_chunks_with_mock_backend(tmp_path: Path) -> None:
    book_root = tmp_path / "workspace" / "book-editor"
    (book_root / "analysis").mkdir(parents=True, exist_ok=True)
    (book_root / "translated").mkdir(parents=True, exist_ok=True)
    (book_root / "logs").mkdir(parents=True, exist_ok=True)
    (book_root / "memory").mkdir(parents=True, exist_ok=True)

    _write_jsonl(
        book_root / "analysis" / "chunks.jsonl",
        [
            {
                "chunk_id": "chunk-1",
                "chapter_id": "chapter-01",
                "page_range": [1, 1],
                "block_ids": ["b1"],
                "chunk_type": "paragraph_group",
                "source_text": "Alpha term appears [1].",
                "footnote_refs": [{"marker": "[1]"}],
            }
        ],
    )
    _write_jsonl(
        book_root / "translated" / "translated_chunks.jsonl",
        [
            {
                "chunk_id": "chunk-1",
                "status": "completed",
                "target_text": "Альфа термин встречается [1].",
            }
        ],
    )
    (book_root / "memory" / "glossary.md").write_text(
        "# Glossary\n\n## Term Table\n| Source term | Target term | POS | Decision | Notes |\n|---|---|---|---|---|\n| Alpha | Альфа | noun | preferred | |\n",
        encoding="utf-8",
    )
    (book_root / "memory" / "style_guide.md").write_text("# Style Guide\n- Keep compact style.\n", encoding="utf-8")
    (book_root / "memory" / "chapter_notes.md").write_text(
        "# Chapter Notes\n\n## Global Notes\n- Keep markers.\n", encoding="utf-8"
    )

    result = run_editorial_pass(
        book_root=book_root,
        backend=MockCodexBackend(),
        options=EditorialOptions(strict_terminology=True, preserve_literalness=True, rewrite_level="light"),
    )
    assert result.edited_chunks == 1
    edited_rows = (book_root / "translated" / "edited_chunks.jsonl").read_text(encoding="utf-8")
    assert "[MOCK_EDIT]" in edited_rows
    assert (book_root / "logs" / "codex_jobs.jsonl").exists()


def test_consistency_pass_writes_conflict_flags(tmp_path: Path) -> None:
    book_root = tmp_path / "workspace" / "book-consistency"
    (book_root / "analysis").mkdir(parents=True, exist_ok=True)
    (book_root / "translated").mkdir(parents=True, exist_ok=True)
    (book_root / "memory").mkdir(parents=True, exist_ok=True)

    _write_jsonl(
        book_root / "analysis" / "chunks.jsonl",
        [
            {
                "chunk_id": "chunk-1",
                "chapter_id": "chapter-01",
                "page_range": [1, 1],
                "block_ids": ["b1"],
                "chunk_type": "paragraph_group",
                "source_text": "Alpha appears here.",
            },
            {
                "chunk_id": "chunk-2",
                "chapter_id": "chapter-01",
                "page_range": [1, 1],
                "block_ids": ["b2"],
                "chunk_type": "paragraph_group",
                "source_text": "Alpha appears here.",
            },
        ],
    )
    _write_jsonl(
        book_root / "translated" / "edited_chunks.jsonl",
        [
            {"chunk_id": "chunk-1", "status": "completed", "target_text": "Альфа появляется здесь."},
            {"chunk_id": "chunk-2", "status": "completed", "target_text": "Здесь появляется альфа-вариант."},
        ],
    )
    (book_root / "memory" / "glossary.md").write_text(
        "# Glossary\n\n## Term Table\n| Source term | Target term | POS | Decision | Notes |\n|---|---|---|---|---|\n| Alpha | Альфа | noun | preferred | |\n",
        encoding="utf-8",
    )

    result = run_consistency_pass(
        book_root=book_root,
        options=ConsistencyOptions(strict_terminology=True, preserve_literalness=False, rewrite_level="medium"),
    )
    assert result.flags_count >= 1
    flags_text = (book_root / "translated" / "consistency_flags.jsonl").read_text(encoding="utf-8")
    assert "conflict" in flags_text or "inconsistency" in flags_text
