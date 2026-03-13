"""Smoke checks for committed PDF fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.pdf.inspector import inspect_pdf


def test_text_fixture_pdf_has_text_layer() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "pdfs" / "text_fixture.pdf"
    report = inspect_pdf(fixture)
    assert report.page_count == 2
    assert report.has_text_layer is True
    assert report.likely_scan is False


def test_scan_fixture_pdf_is_detected_as_likely_scan() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "pdfs" / "scan_fixture.pdf"
    report = inspect_pdf(fixture)
    assert report.page_count == 2
    assert report.has_images is True
    assert report.likely_scan is True
