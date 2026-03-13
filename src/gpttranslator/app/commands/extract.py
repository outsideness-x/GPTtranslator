"""Extract command registration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from ..core.config import load_config
from ..core.logging import get_logger
from ..core.manifest import load_book_manifest, save_book_manifest
from ..core.paths import resolve_workspace_root
from ..pdf.document_graph import DocumentGraphError, build_document_graph, save_document_graph_artifacts
from ..pdf.extractor import PdfExtractionError, extract_pdf_structure, save_extraction_artifacts
from ..pdf.ocr import OcrBranchResult, OcrError, OcrSettings, run_ocr_extraction, save_ocr_artifacts
from ..translation.chunker import ChunkerSettings, ChunkingError, build_translation_chunks, save_chunks_jsonl

_OCR_MODES = {"off", "auto", "force"}


def register(app: typer.Typer) -> None:
    """Register `extract` command."""

    @app.command("extract")
    def extract_command(
        book_id: str = typer.Argument(..., help="Book ID from `gpttranslator init`."),
        chunk_max_chars: int = typer.Option(1200, min=200, help="Maximum source characters per chunk."),
        chunk_max_blocks: int = typer.Option(8, min=1, help="Maximum blocks per chunk."),
        ocr_mode: str = typer.Option(
            "auto",
            "--ocr-mode",
            help="OCR branch mode: off | auto | force. In auto mode, uses inspection report signal.",
        ),
        ocr_language: str = typer.Option("eng", "--ocr-language", help="OCR language passed to local tesseract."),
        ocr_dpi: int = typer.Option(200, "--ocr-dpi", min=72, help="OCR page rasterization DPI."),
    ) -> None:
        """Extract local document structure from source PDF."""
        config = load_config()
        logger = get_logger("commands.extract")

        workspace_root = resolve_workspace_root(config.project_root, config.workspace_dir_name)
        book_root = workspace_root / book_id
        source_pdf = book_root / "input" / "original.pdf"
        manifest_path = book_root / "manifest.json"
        analysis_dir = book_root / "analysis"

        if not book_root.exists() or not book_root.is_dir():
            typer.secho(f"Extract failed: book workspace not found: {book_id}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        if not source_pdf.exists() or not source_pdf.is_file():
            typer.secho(f"Extract failed: source PDF not found: {source_pdf}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        if not manifest_path.exists():
            typer.secho(f"Extract failed: manifest not found: {manifest_path}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        try:
            mode = _normalize_ocr_mode(ocr_mode)
            manifest = load_book_manifest(manifest_path)

            use_ocr, ocr_reason = _resolve_ocr_branch(
                mode=mode,
                analysis_dir=analysis_dir,
                manifest_metadata=manifest.metadata,
            )

            ocr_result: OcrBranchResult | None = None
            ocr_artifact_paths: dict[str, str] = {}

            if use_ocr:
                ocr_result = run_ocr_extraction(
                    pdf_path=source_pdf,
                    analysis_dir=analysis_dir,
                    settings=OcrSettings(language=ocr_language, dpi=ocr_dpi),
                )
                result = ocr_result.extraction_result
                ocr_artifact_paths = save_ocr_artifacts(analysis_dir, ocr_result)
            else:
                result = extract_pdf_structure(source_pdf)

            artifact_paths = save_extraction_artifacts(analysis_dir, result)

            graph = build_document_graph(result)
            graph_paths = save_document_graph_artifacts(analysis_dir, graph)

            chunk_settings = ChunkerSettings(
                max_chars=chunk_max_chars,
                max_blocks=chunk_max_blocks,
            )
            chunks = build_translation_chunks(graph=graph, settings=chunk_settings)
            chunks_path = save_chunks_jsonl(analysis_dir / "chunks.jsonl", chunks)

            manifest.chunks = chunks
            manifest.metadata.setdefault("pipeline", {})["extract"] = "done"
            manifest.metadata["stage"] = "extracted"
            manifest.metadata["extraction"] = {
                **result.summary(),
                "mode": "ocr" if use_ocr else "native",
                "ocr_mode": mode,
                "ocr_decision_reason": ocr_reason,
                "section_count": len(graph.sections),
                "footnote_link_count": len(graph.footnote_links),
                "chunk_count": len(chunks),
                "chunking": {
                    "max_chars": chunk_settings.max_chars,
                    "max_blocks": chunk_settings.max_blocks,
                },
                "artifacts": {
                    "pages": "analysis/pages.jsonl",
                    "blocks": "analysis/blocks.jsonl",
                    "images": "analysis/images.jsonl",
                    "footnotes": "analysis/footnotes.jsonl",
                    "document_graph": "analysis/document_graph.json",
                    "sections": "analysis/sections.jsonl",
                    "chunks": "analysis/chunks.jsonl",
                },
            }
            if use_ocr and ocr_result is not None:
                manifest.metadata["extraction"]["ocr"] = {
                    "language": ocr_language,
                    "dpi": ocr_dpi,
                    "low_confidence_pages": ocr_result.low_confidence_page_count,
                    "low_confidence_blocks": ocr_result.low_confidence_block_count,
                    "warnings": list(ocr_result.warnings),
                }
                manifest.metadata["extraction"]["artifacts"]["ocr_pages"] = "analysis/ocr_pages.jsonl"
                manifest.metadata["extraction"]["artifacts"]["ocr_blocks"] = "analysis/ocr_blocks.jsonl"
            save_book_manifest(manifest_path, manifest)
        except (PdfExtractionError, OcrError, DocumentGraphError, ChunkingError) as exc:
            typer.secho(f"Extract failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        except Exception as exc:
            logger.exception("extract command failed for book_id=%s", book_id)
            typer.secho(f"Extract failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        logger.info("extraction completed: %s", book_root)

        typer.secho("Extraction completed", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID              : {book_id}")
        typer.echo(f"  Mode                 : {'ocr' if use_ocr else 'native'}")
        if use_ocr:
            typer.echo(f"  OCR reason           : {ocr_reason}")
        typer.echo(f"  Pages                : {result.page_count}")
        typer.echo(f"  Blocks               : {len(result.blocks)}")
        typer.echo(f"  Sections             : {len(graph.sections)}")
        typer.echo(f"  Images               : {len(result.images)}")
        typer.echo(f"  Footnotes            : {len(result.footnotes)}")
        typer.echo(f"  Footnote links       : {len(graph.footnote_links)}")
        typer.echo(f"  Chunks               : {len(chunks)}")
        typer.echo(f"  Pages artifact       : {artifact_paths['pages']}")
        typer.echo(f"  Blocks artifact      : {artifact_paths['blocks']}")
        typer.echo(f"  Images artifact      : {artifact_paths['images']}")
        typer.echo(f"  Footnotes artifact   : {artifact_paths['footnotes']}")
        typer.echo(f"  Graph artifact       : {graph_paths['document_graph']}")
        typer.echo(f"  Sections artifact    : {graph_paths['sections']}")
        typer.echo(f"  Chunks artifact      : {chunks_path}")
        if use_ocr:
            typer.echo(f"  OCR pages artifact   : {ocr_artifact_paths['ocr_pages']}")
            typer.echo(f"  OCR blocks artifact  : {ocr_artifact_paths['ocr_blocks']}")
            low_conf_pages = ocr_result.low_confidence_page_count if ocr_result else 0
            low_conf_blocks = ocr_result.low_confidence_block_count if ocr_result else 0
            typer.secho(
                f"  OCR low-confidence   : pages={low_conf_pages}, blocks={low_conf_blocks}",
                fg=typer.colors.YELLOW,
            )

        total_warnings = len(result.warnings) + len(graph.warnings)
        if total_warnings:
            typer.echo(f"  Warnings             : {total_warnings}")


def _normalize_ocr_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode not in _OCR_MODES:
        allowed = ", ".join(sorted(_OCR_MODES))
        raise typer.BadParameter(f"Invalid --ocr-mode '{value}'. Allowed values: {allowed}")
    return mode


def _resolve_ocr_branch(*, mode: str, analysis_dir: Path, manifest_metadata: dict[str, Any]) -> tuple[bool, str]:
    if mode == "off":
        return False, "ocr_mode=off"
    if mode == "force":
        return True, "ocr_mode=force"

    report_path = analysis_dir / "inspection_report.json"
    report_payload = _safe_load_json(report_path)
    report_likely = _extract_likely_scanned_flag(report_payload)
    if report_likely is True:
        return True, "inspection_report.likely_scanned=true"

    inspection_meta = manifest_metadata.get("inspection")
    if isinstance(inspection_meta, dict):
        manifest_likely = _extract_likely_scanned_flag(inspection_meta)
        if manifest_likely is True:
            return True, "manifest.metadata.inspection.likely_scanned=true"

    return False, "auto:no_likely_scanned_signal"


def _extract_likely_scanned_flag(payload: dict[str, Any] | None) -> bool | None:
    if payload is None:
        return None

    for key in ("likely_scanned", "likely_scan"):
        raw = payload.get(key)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"true", "yes", "1"}:
                return True
            if normalized in {"false", "no", "0"}:
                return False
    return None


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
