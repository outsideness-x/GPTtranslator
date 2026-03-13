"""Tests for local build pipeline and `gpttranslator build` command."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.render import BuildOptions, build_translated_book
from gpttranslator.cli import app

runner = CliRunner()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_blank_pdf(path: Path, *, page_count: int = 1, width: float = 595.0, height: float = 842.0) -> None:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=width, height=height)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        writer.write(file)


def _prepare_build_workspace(root: Path, book_id: str, *, bbox: list[float] | None = None) -> Path:
    book_root = root / "workspace" / book_id
    (book_root / "analysis").mkdir(parents=True, exist_ok=True)
    (book_root / "translated").mkdir(parents=True, exist_ok=True)
    (book_root / "output").mkdir(parents=True, exist_ok=True)
    (book_root / "logs").mkdir(parents=True, exist_ok=True)
    (book_root / "input").mkdir(parents=True, exist_ok=True)

    _write_blank_pdf(book_root / "input" / "original.pdf", page_count=1)

    graph_payload = {
        "version": 1,
        "source_pdf": "input/original.pdf",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "pages": [
            {
                "page_num": 1,
                "width": 595.0,
                "height": 842.0,
                "block_ids": ["blk-0001"],
                "section_ids": ["sec-0001"],
                "image_ids": [],
                "reading_order_strategy": "single-column",
                "flags": [],
                "metadata": {},
            }
        ],
        "sections": [
            {
                "section_id": "sec-0001",
                "title": "Chapter 1",
                "level": 1,
                "start_page": 1,
                "end_page": 1,
                "heading_block_id": None,
                "block_ids": ["blk-0001"],
                "confidence": 1.0,
                "flags": [],
            }
        ],
        "blocks": [
            {
                "block_id": "blk-0001",
                "page_num": 1,
                "block_type": "paragraph",
                "text": "Source paragraph",
                "bbox": bbox,
                "reading_order": 1,
                "style_metadata": {"avg_font_size": 11.0},
                "flags": [],
                "section_id": "sec-0001",
                "prev_block_id": None,
                "next_block_id": None,
            }
        ],
        "images": [],
        "footnote_links": [],
        "edges": [],
        "warnings": [],
    }
    (book_root / "analysis" / "document_graph.json").write_text(
        json.dumps(graph_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _write_jsonl(
        book_root / "analysis" / "chunks.jsonl",
        [
            {
                "chunk_id": "chunk-1",
                "chapter_id": "chapter-01",
                "page_range": [1, 1],
                "block_ids": ["blk-0001"],
                "chunk_type": "paragraph_group",
                "source_text": "Source paragraph",
                "footnote_refs": [],
                "glossary_hints": [],
                "metadata": {},
            }
        ],
    )

    _write_jsonl(book_root / "analysis" / "images.jsonl", [])
    _write_jsonl(book_root / "analysis" / "footnotes.jsonl", [])

    return book_root


def test_build_service_prefers_edited_chunks_and_writes_pdf(tmp_path: Path) -> None:
    book_root = _prepare_build_workspace(tmp_path, "book-build-service", bbox=[72.0, 700.0, 520.0, 760.0])

    _write_jsonl(
        book_root / "translated" / "translated_chunks.jsonl",
        [{"chunk_id": "chunk-1", "status": "completed", "target_text": "Базовый перевод."}],
    )
    _write_jsonl(
        book_root / "translated" / "edited_chunks.jsonl",
        [{"chunk_id": "chunk-1", "status": "completed", "target_text": "Редактированный перевод."}],
    )

    result = build_translated_book(book_root=book_root, options=BuildOptions(prefer_edited=True))

    assert result.translated_pdf_path.exists()
    assert result.report_path.exists()
    assert result.mapped_block_count == 1
    assert result.reflow_page_count == 0

    reader = PdfReader(str(result.translated_pdf_path))
    assert len(reader.pages) == 1
    annotations = reader.pages[0].get("/Annots")
    assert annotations is not None
    contents = [str(item.get_object().get("/Contents", "")) for item in annotations]
    assert any("Редактированный" in text for text in contents)


def test_build_service_adds_controlled_reflow_page_when_bbox_missing(tmp_path: Path) -> None:
    book_root = _prepare_build_workspace(tmp_path, "book-build-reflow", bbox=None)

    _write_jsonl(
        book_root / "translated" / "translated_chunks.jsonl",
        [{"chunk_id": "chunk-1", "status": "completed", "target_text": "Текст уходит в controlled reflow."}],
    )

    result = build_translated_book(book_root=book_root, options=BuildOptions(prefer_edited=False))

    assert result.reflow_page_count >= 1
    reader = PdfReader(str(result.translated_pdf_path))
    assert len(reader.pages) == 2


def test_build_command_runs_and_writes_artifacts() -> None:
    with runner.isolated_filesystem():
        root = Path(".")
        book_root = _prepare_build_workspace(root, "book-build-cli", bbox=[72.0, 700.0, 520.0, 760.0])

        _write_jsonl(
            book_root / "translated" / "translated_chunks.jsonl",
            [{"chunk_id": "chunk-1", "status": "completed", "target_text": "CLI перевод."}],
        )

        result = runner.invoke(app, ["build", "book-build-cli"])

        assert result.exit_code == 0
        assert "Build completed" in result.output
        assert (book_root / "output" / "translated_book.pdf").exists()
        assert (book_root / "output" / "build_report.md").exists()
        assert (book_root / "output" / "translation_summary.md").exists()
        assert (book_root / "logs" / "run.log").exists()
