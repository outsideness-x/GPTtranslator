"""Extract command registration."""

from __future__ import annotations

import typer

from ..core.config import load_config
from ..core.logging import get_logger
from ..core.manifest import load_book_manifest, save_book_manifest
from ..core.paths import resolve_workspace_root
from ..pdf.document_graph import DocumentGraphError, build_document_graph, save_document_graph_artifacts
from ..pdf.extractor import PdfExtractionError, extract_pdf_structure, save_extraction_artifacts
from ..translation.chunker import ChunkerSettings, ChunkingError, build_translation_chunks, save_chunks_jsonl


def register(app: typer.Typer) -> None:
    """Register `extract` command."""

    @app.command("extract")
    def extract_command(
        book_id: str = typer.Argument(..., help="Book ID from `gpttranslator init`."),
        chunk_max_chars: int = typer.Option(1200, min=200, help="Maximum source characters per chunk."),
        chunk_max_blocks: int = typer.Option(8, min=1, help="Maximum blocks per chunk."),
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

            manifest = load_book_manifest(manifest_path)
            manifest.chunks = chunks
            manifest.metadata.setdefault("pipeline", {})["extract"] = "done"
            manifest.metadata["stage"] = "extracted"
            manifest.metadata["extraction"] = {
                **result.summary(),
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
            save_book_manifest(manifest_path, manifest)
        except (PdfExtractionError, DocumentGraphError, ChunkingError) as exc:
            typer.secho(f"Extract failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        except Exception as exc:
            logger.exception("extract command failed for book_id=%s", book_id)
            typer.secho(f"Extract failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        logger.info("extraction completed: %s", book_root)

        typer.secho("Extraction completed", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID              : {book_id}")
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

        total_warnings = len(result.warnings) + len(graph.warnings)
        if total_warnings:
            typer.echo(f"  Warnings             : {total_warnings}")
