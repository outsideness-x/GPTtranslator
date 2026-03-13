"""PDF writer stage: apply overlays and controlled reflow pages locally."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText

from .typesetter import AnnotationSpec, ReflowPageSpec, TypesetDocument, TypesettingConfig


@dataclass(frozen=True, slots=True)
class PdfBuildResult:
    """Result of writing translated PDF artifact."""

    output_path: Path
    page_count: int
    annotation_count: int
    reflow_page_count: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


class PdfWriteError(RuntimeError):
    """Raised when translated PDF cannot be written."""


def write_translated_pdf(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    typeset_document: TypesetDocument,
) -> PdfBuildResult:
    """Write translated PDF using source pages + annotation overlays."""

    if not source_pdf_path.exists():
        raise PdfWriteError(f"source PDF not found: {source_pdf_path}")

    try:
        reader = PdfReader(str(source_pdf_path))
    except Exception as exc:  # pragma: no cover - pypdf backend exception
        raise PdfWriteError(f"unable to read source PDF: {exc}") from exc

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    warnings: list[str] = []
    annotation_count = 0

    for annotation in typeset_document.annotations:
        page_index = annotation.page_num - 1
        if page_index < 0 or page_index >= len(writer.pages):
            warnings.append(f"annotation block {annotation.block_id}: page {annotation.page_num} is outside PDF range")
            continue

        added = _add_annotation(
            writer=writer,
            page_index=page_index,
            annotation=annotation,
        )
        if added:
            annotation_count += 1
        else:
            warnings.append(f"annotation block {annotation.block_id}: failed to add FreeText annotation")

    reflow_page_count = 0
    for reflow in typeset_document.reflow_pages:
        reflow_page_count += 1
        reflow_index = _append_reflow_page(writer=writer)
        annotation_count += _populate_reflow_page(
            writer=writer,
            page_index=reflow_index,
            spec=reflow,
            config=typeset_document.config,
            warnings=warnings,
        )

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf_path.open("wb") as file:
        writer.write(file)

    return PdfBuildResult(
        output_path=output_pdf_path,
        page_count=len(writer.pages),
        annotation_count=annotation_count,
        reflow_page_count=reflow_page_count,
        warnings=tuple([*typeset_document.warnings, *warnings]),
    )


def _add_annotation(*, writer: PdfWriter, page_index: int, annotation: AnnotationSpec) -> bool:
    try:
        free_text = FreeText(
            text=annotation.text,
            rect=annotation.rect,
            font="Helvetica",
            font_size=f"{annotation.font_size_pt}pt",
            font_color="000000",
            border_color=None,
            background_color="ffffff",
        )
        writer.add_annotation(page_index, free_text)
        return True
    except Exception:
        return False


def _append_reflow_page(*, writer: PdfWriter) -> int:
    writer.add_blank_page(width=595.0, height=842.0)
    return len(writer.pages) - 1


def _populate_reflow_page(
    *,
    writer: PdfWriter,
    page_index: int,
    spec: ReflowPageSpec,
    config: TypesettingConfig,
    warnings: list[str],
) -> int:
    count = 0

    margins = config.page_margins
    page_width = 595.0
    page_height = 842.0

    title_top = page_height - margins.top
    title_bottom = title_top - 28.0

    title_annotation = AnnotationSpec(
        page_num=page_index + 1,
        rect=(margins.left, title_bottom, page_width - margins.right, title_top),
        text=spec.title,
        font_size_pt=14,
        block_id=f"reflow-title-{page_index + 1}",
        kind="reflow_title",
    )
    if _add_annotation(writer=writer, page_index=page_index, annotation=title_annotation):
        count += 1

    body_top = title_bottom - 8.0

    footnote_height = 0.0
    if spec.footnote_lines and config.footnote_area_policy != "ignore":
        max_footnote_height = page_height * config.footnote_area_ratio
        line_height = 9.0 * config.line_spacing
        dynamic = (len(spec.footnote_lines) * line_height) + 8.0
        footnote_height = min(max_footnote_height, max(28.0, dynamic))

    body_bottom = margins.bottom + footnote_height + (6.0 if footnote_height > 0 else 0.0)
    body_annotation_rect = (margins.left, body_bottom, page_width - margins.right, body_top)

    if body_annotation_rect[3] <= body_annotation_rect[1]:
        warnings.append(f"reflow page {page_index + 1}: body area is invalid")
    elif spec.body_lines:
        body_annotation = AnnotationSpec(
            page_num=page_index + 1,
            rect=body_annotation_rect,
            text="\n".join(spec.body_lines),
            font_size_pt=10,
            block_id=f"reflow-body-{page_index + 1}",
            kind="reflow_body",
        )
        if _add_annotation(writer=writer, page_index=page_index, annotation=body_annotation):
            count += 1

    if footnote_height > 0 and spec.footnote_lines:
        footnote_rect = (
            margins.left,
            margins.bottom,
            page_width - margins.right,
            margins.bottom + footnote_height,
        )
        footnote_annotation = AnnotationSpec(
            page_num=page_index + 1,
            rect=footnote_rect,
            text="\n".join(spec.footnote_lines),
            font_size_pt=9,
            block_id=f"reflow-footnotes-{page_index + 1}",
            kind="reflow_footnotes",
        )
        if _add_annotation(writer=writer, page_index=page_index, annotation=footnote_annotation):
            count += 1
        else:
            warnings.append(f"reflow page {page_index + 1}: failed to add footnote annotation")

    return count
