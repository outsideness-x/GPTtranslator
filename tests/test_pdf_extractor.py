"""Unit-level tests for local PDF extractor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.pdf.extractor import PdfExtractionError, extract_pdf_structure, save_extraction_artifacts

from _pdf_test_utils import write_corrupted_pdf_with_signature, write_simple_text_pdf


def test_extract_pdf_structure_returns_blocks_pages_and_footnotes(tmp_path: Path) -> None:
    source_pdf = tmp_path / "sample.pdf"
    write_simple_text_pdf(source_pdf)

    result = extract_pdf_structure(source_pdf)

    assert result.page_count == 2
    assert len(result.pages) == 2
    assert len(result.blocks) >= 6

    blocks_by_page: dict[int, list[dict[str, object]]] = {}
    for block in result.blocks:
        blocks_by_page.setdefault(block.page_num, []).append(block.to_dict())

    for page_num, blocks in blocks_by_page.items():
        orders = [int(block["reading_order"]) for block in blocks]
        assert sorted(orders) == list(range(1, len(orders) + 1)), f"page {page_num} has broken reading order"

    block_types = {block.block_type for block in result.blocks}
    assert "paragraph" in block_types
    assert "footer" in block_types
    assert "header" in block_types
    assert "footnote_body" in block_types

    block_row = result.blocks[0].to_dict()
    assert {
        "block_id",
        "page_num",
        "block_type",
        "bbox",
        "reading_order",
        "text",
        "style_metadata",
        "flags",
    }.issubset(set(block_row.keys()))

    analysis_dir = tmp_path / "analysis"
    paths = save_extraction_artifacts(analysis_dir, result)
    assert Path(paths["pages"]).exists()
    assert Path(paths["blocks"]).exists()
    assert Path(paths["images"]).exists()
    assert Path(paths["footnotes"]).exists()

    page_rows = [json.loads(line) for line in Path(paths["pages"]).read_text(encoding="utf-8").splitlines() if line]
    assert len(page_rows) == 2


def test_extract_pdf_structure_raises_on_corrupted_pdf(tmp_path: Path) -> None:
    source_pdf = tmp_path / "broken.pdf"
    write_corrupted_pdf_with_signature(source_pdf)

    with pytest.raises(PdfExtractionError):
        extract_pdf_structure(source_pdf)
