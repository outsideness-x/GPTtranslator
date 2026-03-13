"""Unit tests for document graph assembly and validation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _pdf_test_utils import write_pdf_with_caption_and_image, write_simple_text_pdf

from gpttranslator.app.pdf.document_graph import DocumentGraphError, build_document_graph, validate_document_graph
from gpttranslator.app.pdf.extractor import extract_pdf_structure


def test_build_document_graph_creates_sections_adjacency_and_footnote_links(tmp_path: Path) -> None:
    source_pdf = tmp_path / "sample.pdf"
    write_simple_text_pdf(source_pdf)

    result = extract_pdf_structure(source_pdf)
    graph = build_document_graph(result)

    assert len(graph.sections) >= 1
    assert all(block.section_id for block in graph.blocks)

    ordered_blocks = sorted(graph.blocks, key=lambda item: (item.page_num, item.reading_order, item.block_id))
    for index, block in enumerate(ordered_blocks):
        expected_prev = ordered_blocks[index - 1].block_id if index > 0 else None
        expected_next = ordered_blocks[index + 1].block_id if index + 1 < len(ordered_blocks) else None
        assert block.prev_block_id == expected_prev
        assert block.next_block_id == expected_next

    assert any(link.marker_block_id is not None and link.body_block_id is not None for link in graph.footnote_links)

    validate_document_graph(graph)


def test_build_document_graph_links_caption_to_image(tmp_path: Path) -> None:
    source_pdf = tmp_path / "caption-image.pdf"
    write_pdf_with_caption_and_image(source_pdf)

    result = extract_pdf_structure(source_pdf)
    graph = build_document_graph(result)

    assert len(graph.images) >= 1

    linked_images = [image for image in graph.images if image.caption_block_id]
    assert linked_images, "expected at least one caption->image link"

    block_by_id = {block.block_id: block for block in graph.blocks}
    for image in linked_images:
        assert image.caption_confidence is not None
        assert image.caption_confidence > 0.0
        assert image.caption_block_id in block_by_id


def test_validate_document_graph_detects_invalid_references(tmp_path: Path) -> None:
    source_pdf = tmp_path / "sample.pdf"
    write_simple_text_pdf(source_pdf)

    result = extract_pdf_structure(source_pdf)
    graph = build_document_graph(result)

    graph.blocks[0].next_block_id = "missing-block"

    with pytest.raises(DocumentGraphError):
        validate_document_graph(graph)
