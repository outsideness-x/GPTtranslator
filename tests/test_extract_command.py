"""CLI tests for `gpttranslator extract`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.cli import app

from _pdf_test_utils import write_corrupted_pdf_with_signature, write_simple_text_pdf

runner = CliRunner()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_extract_command_writes_jsonl_artifacts_and_updates_manifest() -> None:
    with runner.isolated_filesystem():
        source_pdf = Path("book.pdf")
        write_simple_text_pdf(source_pdf)

        init_result = runner.invoke(app, ["init", str(source_pdf)])
        assert init_result.exit_code == 0

        workspace_root = Path("workspace")
        book_id = next(path.name for path in workspace_root.iterdir() if path.is_dir())

        extract_result = runner.invoke(app, ["extract", book_id])
        assert extract_result.exit_code == 0
        assert "Extraction completed" in extract_result.output
        assert "Blocks" in extract_result.output

        analysis_dir = workspace_root / book_id / "analysis"
        pages_path = analysis_dir / "pages.jsonl"
        blocks_path = analysis_dir / "blocks.jsonl"
        images_path = analysis_dir / "images.jsonl"
        footnotes_path = analysis_dir / "footnotes.jsonl"
        graph_path = analysis_dir / "document_graph.json"
        sections_path = analysis_dir / "sections.jsonl"
        chunks_path = analysis_dir / "chunks.jsonl"

        assert pages_path.exists()
        assert blocks_path.exists()
        assert images_path.exists()
        assert footnotes_path.exists()
        assert graph_path.exists()
        assert sections_path.exists()
        assert chunks_path.exists()

        pages_rows = _read_jsonl(pages_path)
        blocks_rows = _read_jsonl(blocks_path)
        footnote_rows = _read_jsonl(footnotes_path)
        chunk_rows = _read_jsonl(chunks_path)

        assert len(pages_rows) == 2
        assert len(blocks_rows) >= 6
        assert any(row.get("kind") == "body" for row in footnote_rows)
        assert len(chunk_rows) >= 1

        required_block_keys = {
            "block_id",
            "page_num",
            "block_type",
            "bbox",
            "reading_order",
            "text",
            "style_metadata",
            "flags",
        }
        assert required_block_keys.issubset(set(blocks_rows[0].keys()))

        manifest_path = workspace_root / book_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert manifest["metadata"]["pipeline"]["extract"] == "done"
        assert manifest["metadata"]["stage"] == "extracted"
        assert manifest["metadata"]["extraction"]["page_count"] == 2
        assert manifest["metadata"]["extraction"]["block_count"] == len(blocks_rows)
        assert manifest["metadata"]["extraction"]["chunk_count"] == len(chunk_rows)
        assert manifest["metadata"]["extraction"]["artifacts"]["document_graph"] == "analysis/document_graph.json"
        assert manifest["metadata"]["extraction"]["artifacts"]["sections"] == "analysis/sections.jsonl"
        assert manifest["metadata"]["extraction"]["artifacts"]["chunks"] == "analysis/chunks.jsonl"


def test_extract_command_fails_for_unknown_book() -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["extract", "missing-book"])

    assert result.exit_code == 1
    assert "workspace not found" in result.output.lower()


def test_extract_command_handles_corrupted_pdf() -> None:
    with runner.isolated_filesystem():
        source_pdf = Path("broken.pdf")
        write_corrupted_pdf_with_signature(source_pdf)

        init_result = runner.invoke(app, ["init", str(source_pdf)])
        assert init_result.exit_code == 0

        workspace_root = Path("workspace")
        book_id = next(path.name for path in workspace_root.iterdir() if path.is_dir())

        extract_result = runner.invoke(app, ["extract", book_id])
        assert extract_result.exit_code == 1
        assert "extract failed" in extract_result.output.lower()
