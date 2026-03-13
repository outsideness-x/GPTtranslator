"""Build command registration."""

from __future__ import annotations

import json
from typing import Literal, cast

import typer

from ..core.config import load_config
from ..core.manifest import load_book_manifest, save_book_manifest
from ..core.paths import resolve_workspace_root
from ..core.reporting import append_run_log, collect_book_run_summary, ensure_codex_logs, write_translation_summary
from ..render import BuildOptions, build_translated_book


def register(app: typer.Typer) -> None:
    """Register `build` command."""

    @app.command("build")
    def build_command(
        book_id: str = typer.Argument(..., help="Book ID from `gpttranslator init`."),
        prefer_edited: bool = typer.Option(
            True,
            "--prefer-edited/--translated-only",
            help="Use edited chunks first, fallback to translated chunks.",
        ),
        fallback_mode: str = typer.Option(
            "conservative",
            "--fallback-mode",
            help="Fallback mode: conservative|aggressive-reflow.",
        ),
        font_scale_min: float = typer.Option(
            0.85,
            "--font-scale-min",
            min=0.5,
            max=1.5,
            help="Minimum allowed font scale for fitting text.",
        ),
        font_scale_max: float = typer.Option(
            1.15,
            "--font-scale-max",
            min=0.5,
            max=2.0,
            help="Maximum allowed font scale for fitting text.",
        ),
        line_spacing: float = typer.Option(
            1.35,
            "--line-spacing",
            min=1.0,
            max=2.0,
            help="Line spacing multiplier for wrapping and reflow.",
        ),
        page_margin_left: float = typer.Option(36.0, "--page-margin-left", min=0.0, help="Left page margin in pt."),
        page_margin_right: float = typer.Option(36.0, "--page-margin-right", min=0.0, help="Right page margin in pt."),
        page_margin_top: float = typer.Option(36.0, "--page-margin-top", min=0.0, help="Top page margin in pt."),
        page_margin_bottom: float = typer.Option(
            36.0, "--page-margin-bottom", min=0.0, help="Bottom page margin in pt."
        ),
        footnote_area_policy: str = typer.Option(
            "adaptive",
            "--footnote-area-policy",
            help="Footnote area policy: reserve|adaptive|ignore.",
        ),
        footnote_area_ratio: float = typer.Option(
            0.2,
            "--footnote-area-ratio",
            min=0.05,
            max=0.4,
            help="Reserved footnote area ratio of page height.",
        ),
        widow_lines: int = typer.Option(2, "--widow-lines", min=1, help="Minimum widow lines during splitting."),
        orphan_lines: int = typer.Option(2, "--orphan-lines", min=1, help="Minimum orphan lines during splitting."),
        reflow_page_char_budget: int = typer.Option(
            3200,
            "--reflow-page-char-budget",
            min=500,
            help="Character budget per controlled reflow page.",
        ),
    ) -> None:
        """Build translated PDF locally from translated artifacts and source graphics."""

        config = load_config()
        workspace_root = resolve_workspace_root(config.project_root, config.workspace_dir_name)
        book_root = workspace_root / book_id

        if not book_root.exists() or not book_root.is_dir():
            typer.secho(f"Build failed: book workspace not found: {book_root}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        append_run_log(
            book_root=book_root,
            stage="build",
            status="started",
            message="Build stage started.",
            details={
                "prefer_edited": prefer_edited,
                "fallback_mode": fallback_mode,
            },
        )
        ensure_codex_logs(book_root)

        try:
            normalized_mode = _parse_fallback_mode(fallback_mode)
            normalized_footnote_policy = _parse_footnote_policy(footnote_area_policy)
            result = build_translated_book(
                book_root=book_root,
                options=BuildOptions(
                    prefer_edited=prefer_edited,
                    fallback_mode=normalized_mode,
                    font_scale_min=font_scale_min,
                    font_scale_max=font_scale_max,
                    line_spacing=line_spacing,
                    page_margin_left=page_margin_left,
                    page_margin_right=page_margin_right,
                    page_margin_top=page_margin_top,
                    page_margin_bottom=page_margin_bottom,
                    footnote_area_policy=normalized_footnote_policy,
                    footnote_area_ratio=footnote_area_ratio,
                    widow_lines=widow_lines,
                    orphan_lines=orphan_lines,
                    reflow_page_char_budget=reflow_page_char_budget,
                ),
            )
        except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
            append_run_log(
                book_root=book_root,
                stage="build",
                status="failed",
                message=f"Build stage failed: {exc}",
            )
            typer.secho(f"Build failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        summary = collect_book_run_summary(book_root)
        summary_path = write_translation_summary(book_root, summary)

        manifest_path = book_root / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = load_book_manifest(manifest_path)
                pipeline = manifest.metadata.setdefault("pipeline", {})
                pipeline["build"] = "done"
                manifest.metadata["stage"] = "built"
                manifest.metadata["build"] = {
                    "output_pdf": "output/translated_book.pdf",
                    "build_report": "output/build_report.md",
                    "page_count": result.page_count,
                    "warning_count": len(result.warnings),
                    "summary_artifact": "output/translation_summary.md",
                }
                save_book_manifest(manifest_path, manifest)
            except Exception:
                pass

        typer.secho("Build completed", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID                     : {book_id}")
        typer.echo(f"  Prefer edited chunks        : {prefer_edited}")
        typer.echo(f"  Fallback mode               : {normalized_mode}")
        typer.echo(f"  Font scale min/max          : {font_scale_min}/{font_scale_max}")
        typer.echo(f"  Line spacing                : {line_spacing}")
        typer.echo(
            f"  Page margins (L,R,T,B)      : {page_margin_left}, {page_margin_right}, {page_margin_top}, {page_margin_bottom}"
        )
        typer.echo(f"  Footnote policy             : {normalized_footnote_policy} ({footnote_area_ratio})")
        typer.echo(f"  Widow/orphan lines          : {widow_lines}/{orphan_lines}")
        typer.echo(f"  Output PDF pages            : {result.page_count}")
        typer.echo(f"  Overlay annotations         : {result.annotation_count}")
        typer.echo(f"  Controlled reflow pages     : {result.reflow_page_count}")
        typer.echo(f"  Translated chunks mapped    : {result.translated_chunk_count}")
        typer.echo(f"  Text blocks mapped          : {result.mapped_block_count}")
        typer.echo(f"  Image assets copied         : {result.copied_asset_count}")
        typer.echo(f"  Image assets missing        : {result.missing_asset_count}")
        typer.echo(f"  Output PDF                  : {result.translated_pdf_path}")
        typer.echo(f"  Build report                : {result.report_path}")
        typer.echo(f"  Assets manifest             : {result.assets_manifest_path}")
        typer.echo(f"  Translation summary         : {summary_path}")
        typer.echo(f"  Warnings                    : {len(result.warnings)}")

        append_run_log(
            book_root=book_root,
            stage="build",
            status="completed",
            message="Build stage completed.",
            details={
                "pdf_pages": result.page_count,
                "warnings": len(result.warnings),
                "summary_path": str(summary_path),
            },
        )


def _parse_fallback_mode(raw_value: str) -> Literal["conservative", "aggressive_reflow"]:
    normalized = raw_value.strip().lower().replace("-", "_")
    allowed = {"conservative", "aggressive_reflow"}
    if normalized not in allowed:
        raise ValueError("fallback mode must be one of: conservative, aggressive-reflow")
    return cast(Literal["conservative", "aggressive_reflow"], normalized)


def _parse_footnote_policy(raw_value: str) -> Literal["reserve", "adaptive", "ignore"]:
    normalized = raw_value.strip().lower()
    allowed = {"reserve", "adaptive", "ignore"}
    if normalized not in allowed:
        raise ValueError("footnote area policy must be one of: reserve, adaptive, ignore")
    return cast(Literal["reserve", "adaptive", "ignore"], normalized)
