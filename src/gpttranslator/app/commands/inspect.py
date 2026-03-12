"""Inspect command registration."""

from __future__ import annotations

import typer

from ..core.config import load_config
from ..core.logging import get_logger
from ..core.manifest import load_book_manifest, save_book_manifest
from ..core.paths import resolve_workspace_root
from ..pdf.inspector import PdfInspectionError, inspect_pdf, save_inspection_report


def register(app: typer.Typer) -> None:
    """Register `inspect` command."""

    @app.command("inspect")
    def inspect_command(book_id: str = typer.Argument(..., help="Book ID from `gpttranslator init`.")) -> None:
        """Inspect source PDF and save analysis report."""
        config = load_config()
        logger = get_logger("commands.inspect")

        workspace_root = resolve_workspace_root(config.project_root, config.workspace_dir_name)
        book_root = workspace_root / book_id
        source_pdf = book_root / "input" / "original.pdf"
        manifest_path = book_root / "manifest.json"
        report_path = book_root / "analysis" / "inspection_report.json"

        if not book_root.exists() or not book_root.is_dir():
            typer.secho(f"Inspect failed: book workspace not found: {book_id}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        if not manifest_path.exists():
            typer.secho(f"Inspect failed: manifest not found: {manifest_path}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        try:
            report = inspect_pdf(source_pdf)
            save_inspection_report(report_path, report)

            manifest = load_book_manifest(manifest_path)
            manifest.metadata["inspection"] = report.to_dict()
            manifest.metadata.setdefault("pipeline", {})["inspect"] = "done"
            manifest.metadata["stage"] = "inspected"
            save_book_manifest(manifest_path, manifest)
        except PdfInspectionError as exc:
            typer.secho(f"Inspect failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        except Exception as exc:
            logger.exception("inspect command failed for book_id=%s", book_id)
            typer.secho(f"Inspect failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        logger.info("inspection completed: %s", report_path)

        typer.secho("Inspection completed", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID              : {book_id}")
        typer.echo(f"  Pages                : {report.page_count}")
        typer.echo(f"  Text layer           : {_yes_no(report.has_text_layer)}")
        typer.echo(f"  Likely scan          : {_yes_no(report.likely_scan)}")
        typer.echo(f"  Images               : {_yes_no(report.has_images)}")
        typer.echo(f"  Footnotes/endnotes   : {_yes_no(report.possible_footnotes_or_endnotes)}")
        typer.echo(f"  Headers/footers      : {_yes_no(report.has_headers_or_footers)}")
        typer.echo(f"  Multi-column pages   : {_yes_no(report.has_multi_column_pages)}")
        typer.echo(f"  Main page sizes      : {_format_page_sizes(report.main_page_sizes)}")
        typer.echo(f"  Report               : {report_path}")

        if report.warnings:
            typer.echo(f"  Warnings             : {len(report.warnings)} (see inspection_report.json)")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _format_page_sizes(sizes: list[dict[str, float | int]]) -> str:
    if not sizes:
        return "n/a"

    formatted: list[str] = []
    for item in sizes:
        width = item.get("width")
        height = item.get("height")
        count = item.get("count")
        formatted.append(f"{width}x{height} ({count}p)")
    return ", ".join(formatted)
