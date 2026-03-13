"""Smoke tests for local OCR branch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _pdf_test_utils import write_simple_text_pdf

from gpttranslator.app.pdf.ocr import OcrSettings, run_ocr_extraction, save_ocr_artifacts


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_run_ocr_extraction_fallback_without_external_tools(tmp_path: Path, monkeypatch) -> None:
    source_pdf = tmp_path / "book.pdf"
    write_simple_text_pdf(source_pdf)

    monkeypatch.setattr("gpttranslator.app.pdf.ocr.shutil.which", lambda _: None)

    analysis_dir = tmp_path / "analysis"
    result = run_ocr_extraction(pdf_path=source_pdf, analysis_dir=analysis_dir, settings=OcrSettings(language="eng"))

    assert result.extraction_result.page_count == 2
    assert len(result.ocr_pages) == 2
    assert len(result.ocr_blocks) >= 2
    assert result.low_confidence_page_count >= 1
    assert result.low_confidence_block_count >= 1
    assert any("tesseract binary not found" in warning.lower() for warning in result.warnings)


def test_save_ocr_artifacts_writes_expected_jsonl(tmp_path: Path, monkeypatch) -> None:
    source_pdf = tmp_path / "book.pdf"
    write_simple_text_pdf(source_pdf)

    monkeypatch.setattr("gpttranslator.app.pdf.ocr.shutil.which", lambda _: None)

    analysis_dir = tmp_path / "analysis"
    result = run_ocr_extraction(pdf_path=source_pdf, analysis_dir=analysis_dir, settings=OcrSettings())
    paths = save_ocr_artifacts(analysis_dir, result)

    ocr_pages_path = Path(paths["ocr_pages"])
    ocr_blocks_path = Path(paths["ocr_blocks"])
    assert ocr_pages_path.exists()
    assert ocr_blocks_path.exists()

    pages = _read_jsonl(ocr_pages_path)
    blocks = _read_jsonl(ocr_blocks_path)
    assert len(pages) == 2
    assert len(blocks) >= 2
    assert "low_confidence" in pages[0]
    assert "confidence" in blocks[0]
