"""Unit-level tests for local PDF inspector."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _pdf_test_utils import write_corrupted_pdf_with_signature, write_simple_text_pdf

from gpttranslator.app.pdf.inspector import PdfInspectionError, inspect_pdf, save_inspection_report


def test_inspect_pdf_detects_text_and_structure(tmp_path: Path) -> None:
    source_pdf = tmp_path / "sample.pdf"
    write_simple_text_pdf(source_pdf)

    report = inspect_pdf(source_pdf)

    assert report.page_count == 2
    assert report.has_text_layer is True
    assert report.likely_scan is False
    assert report.has_images is False
    assert report.possible_footnotes_or_endnotes is True
    assert report.has_headers_or_footers is True
    assert report.has_multi_column_pages is False
    assert report.main_page_sizes[0]["count"] == 2

    report_path = tmp_path / "inspection_report.json"
    save_inspection_report(report_path, report)

    stored = json.loads(report_path.read_text(encoding="utf-8"))
    assert stored["page_count"] == 2
    assert stored["has_text_layer"] is True
    assert stored["likely_scanned"] == stored["likely_scan"]


def test_inspect_pdf_raises_on_corrupted_pdf(tmp_path: Path) -> None:
    source_pdf = tmp_path / "broken.pdf"
    write_corrupted_pdf_with_signature(source_pdf)

    with pytest.raises(PdfInspectionError):
        inspect_pdf(source_pdf)
