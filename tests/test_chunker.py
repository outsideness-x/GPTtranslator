"""Unit tests for local chunker."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _pdf_test_utils import write_multi_paragraph_pdf, write_simple_text_pdf

from gpttranslator.app.pdf.document_graph import build_document_graph
from gpttranslator.app.pdf.extractor import extract_pdf_structure
from gpttranslator.app.translation.chunker import (
    ChunkerSettings,
    ChunkingError,
    build_translation_chunks,
    save_chunks_jsonl,
    validate_chunks,
)


def test_chunker_builds_chunks_with_required_fields_and_refs(tmp_path: Path) -> None:
    source_pdf = tmp_path / "sample.pdf"
    write_simple_text_pdf(source_pdf)

    extraction = extract_pdf_structure(source_pdf)
    graph = build_document_graph(extraction)

    chunks = build_translation_chunks(graph=graph, settings=ChunkerSettings(max_chars=1200, max_blocks=4))
    assert chunks

    block_by_id = {block.block_id: block for block in graph.blocks}

    for chunk in chunks:
        row = chunk.to_dict()
        required = {
            "chunk_id",
            "chapter_id",
            "page_range",
            "block_ids",
            "chunk_type",
            "source_text",
            "local_context_before",
            "local_context_after",
            "footnote_refs",
            "glossary_hints",
        }
        assert required.issubset(set(row.keys()))

        member_types = {block_by_id[block_id].block_type for block_id in chunk.block_ids}
        if chunk.chunk_type == "paragraph_group":
            assert member_types.issubset({"paragraph"})
        elif chunk.chunk_type == "caption":
            assert member_types.issubset({"caption"})
        elif chunk.chunk_type == "footnote":
            assert member_types.issubset({"footnote_body", "footnote_marker"})
        elif chunk.chunk_type == "heading":
            assert member_types.issubset({"heading"})
        elif chunk.chunk_type == "auxiliary":
            assert member_types.issubset({"header", "footer", "image_anchor"})

    assert any(chunk.chunk_type == "footnote" for chunk in chunks)
    assert any(chunk.footnote_refs for chunk in chunks)

    path = tmp_path / "chunks.jsonl"
    save_chunks_jsonl(path, chunks)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == len(chunks)


def test_chunker_respects_max_blocks_setting(tmp_path: Path) -> None:
    source_pdf = tmp_path / "paragraphs.pdf"
    write_multi_paragraph_pdf(source_pdf, paragraph_count=7)

    extraction = extract_pdf_structure(source_pdf)
    graph = build_document_graph(extraction)

    chunks = build_translation_chunks(graph=graph, settings=ChunkerSettings(max_chars=5000, max_blocks=2))

    paragraph_chunks = [chunk for chunk in chunks if chunk.chunk_type == "paragraph_group"]
    assert paragraph_chunks
    assert all(len(chunk.block_ids) <= 2 for chunk in paragraph_chunks)


def test_chunk_validation_catches_invalid_mixed_types(tmp_path: Path) -> None:
    source_pdf = tmp_path / "sample.pdf"
    write_simple_text_pdf(source_pdf)

    extraction = extract_pdf_structure(source_pdf)
    graph = build_document_graph(extraction)
    chunks = build_translation_chunks(graph=graph)

    broken = chunks[0]
    broken.chunk_type = "paragraph_group"

    wrong_block = next(
        block.block_id for block in graph.blocks if block.block_type in {"header", "footer", "image_anchor"}
    )
    broken.block_ids = [wrong_block]

    with pytest.raises(ChunkingError):
        validate_chunks(chunks=chunks, graph=graph)
