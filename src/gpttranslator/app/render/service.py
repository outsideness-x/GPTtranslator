"""Render/build orchestration for local translated PDF assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..core.logging import get_logger
from .assets import AssetBundle, collect_image_assets
from .composer import BuildComposition, compose_document
from .pdf_writer import PdfBuildResult, write_translated_pdf
from .typesetter import (
    PageMargins,
    TypesetDocument,
    TypesettingConfig,
    build_typesetting_config,
    typeset_composition,
)

logger = get_logger("render.service")

FallbackMode = Literal["conservative", "aggressive_reflow"]
FootnoteAreaPolicy = Literal["reserve", "adaptive", "ignore"]


@dataclass(frozen=True, slots=True)
class BuildOptions:
    """Local build options for output PDF assembly."""

    prefer_edited: bool = True
    fallback_mode: FallbackMode = "conservative"
    font_scale_min: float = 0.85
    font_scale_max: float = 1.15
    line_spacing: float = 1.35
    page_margin_left: float = 36.0
    page_margin_right: float = 36.0
    page_margin_top: float = 36.0
    page_margin_bottom: float = 36.0
    footnote_area_policy: FootnoteAreaPolicy = "adaptive"
    footnote_area_ratio: float = 0.2
    widow_lines: int = 2
    orphan_lines: int = 2
    reflow_page_char_budget: int = 3200

    def to_typesetting_config(self) -> TypesettingConfig:
        return build_typesetting_config(
            fallback_mode=self.fallback_mode,
            font_scale_min=self.font_scale_min,
            font_scale_max=self.font_scale_max,
            line_spacing=self.line_spacing,
            margins=PageMargins(
                left=self.page_margin_left,
                right=self.page_margin_right,
                top=self.page_margin_top,
                bottom=self.page_margin_bottom,
            ),
            footnote_area_policy=self.footnote_area_policy,
            footnote_area_ratio=self.footnote_area_ratio,
            widow_lines=self.widow_lines,
            orphan_lines=self.orphan_lines,
            reflow_page_char_budget=self.reflow_page_char_budget,
        )


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Build stage final artifacts and summary metrics."""

    translated_pdf_path: Path
    report_path: Path
    assets_manifest_path: Path
    page_count: int
    annotation_count: int
    reflow_page_count: int
    translated_chunk_count: int
    mapped_block_count: int
    copied_asset_count: int
    missing_asset_count: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


def build_translated_book(*, book_root: Path, options: BuildOptions) -> BuildResult:
    """Build translated PDF + report using local data only (no Codex calls)."""

    output_dir = book_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    typesetting_config = options.to_typesetting_config()
    composition = compose_document(book_root=book_root, prefer_edited=options.prefer_edited)
    assets = collect_image_assets(book_root)
    typeset = typeset_composition(
        composition,
        config=typesetting_config,
    )

    translated_pdf_path = output_dir / "translated_book.pdf"
    pdf_result = write_translated_pdf(
        source_pdf_path=composition.source_pdf_path,
        output_pdf_path=translated_pdf_path,
        typeset_document=typeset,
    )

    warnings = tuple(
        [
            *composition.warnings,
            *assets.warnings,
            *typeset.warnings,
            *pdf_result.warnings,
        ]
    )

    report_path = output_dir / "build_report.md"
    report_text = _render_build_report(
        book_id=book_root.name,
        options=options,
        composition=composition,
        assets=assets,
        typeset=typeset,
        pdf_result=pdf_result,
        warnings=warnings,
    )
    report_path.write_text(report_text, encoding="utf-8")

    logger.info(
        "build completed: book_id=%s pages=%s annotations=%s reflow_pages=%s assets=%s/%s mode=%s",
        book_root.name,
        pdf_result.page_count,
        pdf_result.annotation_count,
        pdf_result.reflow_page_count,
        assets.copied_count,
        len(assets.records),
        options.fallback_mode,
    )

    return BuildResult(
        translated_pdf_path=translated_pdf_path,
        report_path=report_path,
        assets_manifest_path=assets.manifest_path,
        page_count=pdf_result.page_count,
        annotation_count=pdf_result.annotation_count,
        reflow_page_count=pdf_result.reflow_page_count,
        translated_chunk_count=composition.translated_chunk_count,
        mapped_block_count=composition.mapped_block_count,
        copied_asset_count=assets.copied_count,
        missing_asset_count=assets.missing_count,
        warnings=warnings,
    )


def _render_build_report(
    *,
    book_id: str,
    options: BuildOptions,
    composition: BuildComposition,
    assets: AssetBundle,
    typeset: TypesetDocument,
    pdf_result: PdfBuildResult,
    warnings: tuple[str, ...],
) -> str:
    metrics = typeset.metrics
    lines: list[str] = [
        f"# Build Report: {book_id}",
        "",
        "## Summary",
        "",
        f"- Translation source: `{composition.translation_source}`",
        f"- Translated chunks mapped: **{composition.translated_chunk_count}**",
        f"- Text blocks mapped: **{composition.mapped_block_count}**",
        f"- Overlay annotations written: **{metrics.overlay_annotation_count}**",
        f"- Reflow pages added: **{metrics.reflow_page_count}**",
        f"- Reflow page breaks: **{metrics.reflow_page_break_count}**",
        f"- Overflow blocks: **{metrics.overflow_block_count}**",
        f"- Multi-page blocks: **{metrics.multi_page_block_count}**",
        f"- Widow/orphan adjustments: **{metrics.widow_orphan_adjustments}**",
        f"- Page-level footnote annotations: **{metrics.footnote_annotation_count}**",
        f"- Footnote overflows to reflow: **{metrics.footnote_overflow_count}**",
        f"- Caption annotations: **{metrics.caption_annotation_count}**",
        f"- Output PDF pages: **{pdf_result.page_count}**",
        f"- Image assets copied: **{assets.copied_count}**",
        f"- Image assets missing: **{assets.missing_count}**",
        f"- Output PDF: `{pdf_result.output_path}`",
        f"- Assets dir: `{assets.assets_dir}`",
        f"- Assets manifest: `{assets.manifest_path}`",
        "",
        "## Typesetting Config",
        "",
        "| Key | Value |",
        "|---|---|",
        f"| fallback_mode | `{options.fallback_mode}` |",
        f"| font_scale_min | `{options.font_scale_min}` |",
        f"| font_scale_max | `{options.font_scale_max}` |",
        f"| line_spacing | `{options.line_spacing}` |",
        f"| page_margins | `{options.page_margin_left}, {options.page_margin_right}, {options.page_margin_top}, {options.page_margin_bottom}` |",
        f"| footnote_area_policy | `{options.footnote_area_policy}` |",
        f"| footnote_area_ratio | `{options.footnote_area_ratio}` |",
        f"| widow_lines | `{options.widow_lines}` |",
        f"| orphan_lines | `{options.orphan_lines}` |",
        f"| reflow_page_char_budget | `{options.reflow_page_char_budget}` |",
        "",
        "## Notes",
        "",
        "- Build is fully local and does not call `codex`.",
        "- Text overlays are deterministic and repeatable for the same inputs.",
        "- Controlled reflow is used for overflow, invalid geometry, and multi-page continuation.",
        "- Footnotes are handled on page level with configurable reserved area policy.",
    ]

    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings[:250]:
            lines.append(f"- {warning}")

    return "\n".join(lines).rstrip() + "\n"
