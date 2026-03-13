"""Typesetting stage for deterministic local reflow and layout control."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field, replace
from typing import Iterable, Literal

from .composer import BuildComposition, ComposedPage, ComposedTextBlock

FallbackMode = Literal["conservative", "aggressive_reflow"]
FootnoteAreaPolicy = Literal["reserve", "adaptive", "ignore"]

_PAGE_WIDTH_PT = 595.0
_PAGE_HEIGHT_PT = 842.0


@dataclass(frozen=True, slots=True)
class PageMargins:
    """Page margin configuration used for reflow pages and constraints."""

    left: float = 36.0
    right: float = 36.0
    top: float = 36.0
    bottom: float = 36.0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.left < 0 or self.right < 0 or self.top < 0 or self.bottom < 0:
            errors.append("page margins must be >= 0")
        if self.left + self.right >= _PAGE_WIDTH_PT:
            errors.append("horizontal margins are too large for page width")
        if self.top + self.bottom >= _PAGE_HEIGHT_PT:
            errors.append("vertical margins are too large for page height")
        return errors


@dataclass(frozen=True, slots=True)
class TypesettingConfig:
    """Deterministic typesetting and reflow controls."""

    fallback_mode: FallbackMode = "conservative"
    font_scale_min: float = 0.85
    font_scale_max: float = 1.15
    line_spacing: float = 1.35
    page_margins: PageMargins = field(default_factory=PageMargins)
    footnote_area_policy: FootnoteAreaPolicy = "adaptive"
    footnote_area_ratio: float = 0.2
    widow_lines: int = 2
    orphan_lines: int = 2
    reflow_page_char_budget: int = 3200

    def validate(self) -> list[str]:
        errors = self.page_margins.validate()
        if not (0.5 <= self.font_scale_min <= 1.5):
            errors.append("font_scale_min must be in [0.5, 1.5]")
        if not (0.5 <= self.font_scale_max <= 2.0):
            errors.append("font_scale_max must be in [0.5, 2.0]")
        if self.font_scale_min > self.font_scale_max:
            errors.append("font_scale_min must be <= font_scale_max")
        if not (1.0 <= self.line_spacing <= 2.0):
            errors.append("line_spacing must be in [1.0, 2.0]")
        if not (0.05 <= self.footnote_area_ratio <= 0.4):
            errors.append("footnote_area_ratio must be in [0.05, 0.4]")
        if self.widow_lines < 1:
            errors.append("widow_lines must be >= 1")
        if self.orphan_lines < 1:
            errors.append("orphan_lines must be >= 1")
        if self.reflow_page_char_budget < 500:
            errors.append("reflow_page_char_budget must be >= 500")
        return errors


@dataclass(frozen=True, slots=True)
class AnnotationSpec:
    """FreeText annotation payload for one translated block."""

    page_num: int
    rect: tuple[float, float, float, float]
    text: str
    font_size_pt: int
    block_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class ReflowPageSpec:
    """Controlled reflow page payload with page-level footnote separation."""

    title: str
    body_lines: tuple[str, ...]
    footnote_lines: tuple[str, ...] = tuple()


@dataclass(frozen=True, slots=True)
class TypesetMetrics:
    """Detailed deterministic metrics for build reporting."""

    overlay_annotation_count: int
    footnote_annotation_count: int
    caption_annotation_count: int
    overflow_block_count: int
    reflow_page_count: int
    reflow_page_break_count: int
    widow_orphan_adjustments: int
    multi_page_block_count: int
    footnote_overflow_count: int


@dataclass(frozen=True, slots=True)
class TypesetDocument:
    """Typesetting output consumed by PDF writer."""

    annotations: tuple[AnnotationSpec, ...]
    reflow_pages: tuple[ReflowPageSpec, ...]
    config: TypesettingConfig
    metrics: TypesetMetrics
    warnings: tuple[str, ...] = field(default_factory=tuple)


class TypesetterError(RuntimeError):
    """Raised when composition cannot be typeset."""


def build_typesetting_config(
    *,
    fallback_mode: FallbackMode,
    font_scale_min: float,
    font_scale_max: float,
    line_spacing: float,
    margins: PageMargins,
    footnote_area_policy: FootnoteAreaPolicy,
    footnote_area_ratio: float,
    widow_lines: int,
    orphan_lines: int,
    reflow_page_char_budget: int,
) -> TypesettingConfig:
    """Build config object for service/CLI with centralized validation."""

    return TypesettingConfig(
        fallback_mode=fallback_mode,
        font_scale_min=font_scale_min,
        font_scale_max=font_scale_max,
        line_spacing=line_spacing,
        page_margins=margins,
        footnote_area_policy=footnote_area_policy,
        footnote_area_ratio=footnote_area_ratio,
        widow_lines=widow_lines,
        orphan_lines=orphan_lines,
        reflow_page_char_budget=reflow_page_char_budget,
    )


@dataclass(slots=True)
class _FitResult:
    fitted_text: str
    overflow_text: str
    used_font_size: float
    widow_orphan_adjusted: bool


@dataclass(slots=True)
class _ReflowItem:
    source_block_id: str
    source_page_num: int
    kind: str
    text: str


def typeset_composition(
    composition: BuildComposition,
    *,
    config: TypesettingConfig | None = None,
    reflow_page_char_budget: int | None = None,
) -> TypesetDocument:
    """Typeset translated content into overlay annotations and controlled reflow pages."""

    resolved_config = config or TypesettingConfig()
    if reflow_page_char_budget is not None:
        resolved_config = replace(resolved_config, reflow_page_char_budget=reflow_page_char_budget)

    config_errors = resolved_config.validate()
    if config_errors:
        message = "; ".join(config_errors)
        raise TypesetterError(f"typesetting config is invalid: {message}")

    annotations: list[AnnotationSpec] = []
    warnings: list[str] = []
    reflow_items: list[_ReflowItem] = []

    overflow_block_ids: set[str] = set()
    multi_page_block_ids: set[str] = set()
    widow_orphan_adjustments = 0
    footnote_overflow_count = 0

    footnote_annotation_count = 0
    caption_annotation_count = 0

    for page in composition.pages:
        page_items = _typeset_source_page(
            page=page,
            config=resolved_config,
        )

        annotations.extend(page_items.annotations)
        reflow_items.extend(page_items.reflow_items)
        warnings.extend(page_items.warnings)
        widow_orphan_adjustments += page_items.widow_orphan_adjustments
        footnote_annotation_count += page_items.footnote_annotation_count
        caption_annotation_count += page_items.caption_annotation_count

        overflow_block_ids.update(page_items.overflow_block_ids)
        multi_page_block_ids.update(page_items.multi_page_block_ids)
        footnote_overflow_count += page_items.footnote_overflow_count

    for block in composition.reflow_blocks:
        reflow_items.append(
            _ReflowItem(
                source_block_id=block.block_id,
                source_page_num=block.page_num,
                kind=block.block_type,
                text=_normalize_text(block.text),
            )
        )
        overflow_block_ids.add(block.block_id)

    reflow_pages, reflow_page_breaks, reflow_page_multi_blocks, reflow_warnings, reflow_widow_orphan_adjustments = (
        _build_reflow_pages(
            items=reflow_items,
            config=resolved_config,
        )
    )
    warnings.extend(reflow_warnings)
    widow_orphan_adjustments += reflow_widow_orphan_adjustments
    multi_page_block_ids.update(reflow_page_multi_blocks)

    metrics = TypesetMetrics(
        overlay_annotation_count=len(annotations),
        footnote_annotation_count=footnote_annotation_count,
        caption_annotation_count=caption_annotation_count,
        overflow_block_count=len(overflow_block_ids),
        reflow_page_count=len(reflow_pages),
        reflow_page_break_count=reflow_page_breaks,
        widow_orphan_adjustments=widow_orphan_adjustments,
        multi_page_block_count=len(multi_page_block_ids),
        footnote_overflow_count=footnote_overflow_count,
    )

    return TypesetDocument(
        annotations=tuple(annotations),
        reflow_pages=tuple(reflow_pages),
        config=resolved_config,
        metrics=metrics,
        warnings=tuple(warnings),
    )


@dataclass(slots=True)
class _PageTypesetResult:
    annotations: list[AnnotationSpec]
    reflow_items: list[_ReflowItem]
    warnings: list[str]
    widow_orphan_adjustments: int
    footnote_annotation_count: int
    caption_annotation_count: int
    overflow_block_ids: set[str]
    multi_page_block_ids: set[str]
    footnote_overflow_count: int


def _typeset_source_page(*, page: ComposedPage, config: TypesettingConfig) -> _PageTypesetResult:
    annotations: list[AnnotationSpec] = []
    warnings: list[str] = []
    reflow_items: list[_ReflowItem] = []
    widow_orphan_adjustments = 0
    caption_annotation_count = 0
    footnote_annotation_count = 0
    overflow_block_ids: set[str] = set()
    multi_page_block_ids: set[str] = set()
    footnote_overflow_count = 0

    overlay_blocks = list(page.overlay_blocks)
    footnote_blocks = [block for block in overlay_blocks if block.block_type in {"footnote_body", "footnote_marker"}]
    content_blocks = [block for block in overlay_blocks if block.block_type not in {"footnote_body", "footnote_marker"}]

    footnote_lines = _collect_page_footnotes(page=page, translated_blocks=footnote_blocks)
    footnote_reserved_height = _reserved_footnote_height(
        page_height=page.height,
        footnote_line_count=len(footnote_lines),
        config=config,
    )
    footnote_top = config.page_margins.bottom + footnote_reserved_height

    caption_overflow: list[_ReflowItem] = []
    body_overflow: list[_ReflowItem] = []

    for block in content_blocks:
        if block.bbox is None:
            item = _ReflowItem(
                source_block_id=block.block_id,
                source_page_num=block.page_num,
                kind=block.block_type,
                text=_normalize_text(block.text),
            )
            if block.block_type == "caption":
                caption_overflow.append(item)
            else:
                body_overflow.append(item)
            overflow_block_ids.add(block.block_id)
            continue

        rect = _normalized_rect(block.bbox, page_width=page.width, page_height=page.height)
        if rect is None:
            item = _ReflowItem(
                source_block_id=block.block_id,
                source_page_num=block.page_num,
                kind=block.block_type,
                text=_normalize_text(block.text),
            )
            if block.block_type == "caption":
                caption_overflow.append(item)
            else:
                body_overflow.append(item)
            overflow_block_ids.add(block.block_id)
            warnings.append(f"block {block.block_id}: invalid bbox, moved to reflow")
            continue

        rect = _clip_rect_for_footnote_area(
            rect=rect,
            block=block,
            footnote_top=footnote_top,
        )
        if rect is None:
            item = _ReflowItem(
                source_block_id=block.block_id,
                source_page_num=block.page_num,
                kind=block.block_type,
                text=_normalize_text(block.text),
            )
            if block.block_type == "caption":
                caption_overflow.append(item)
            else:
                body_overflow.append(item)
            overflow_block_ids.add(block.block_id)
            warnings.append(f"block {block.block_id}: no drawable area after footnote reservation")
            continue

        fit = _fit_text_into_rect(
            text=block.text,
            rect=rect,
            base_font_size=block.font_size,
            config=config,
        )
        if fit.widow_orphan_adjusted:
            widow_orphan_adjustments += 1

        if fit.fitted_text.strip():
            annotations.append(
                AnnotationSpec(
                    page_num=block.page_num,
                    rect=rect,
                    text=fit.fitted_text,
                    font_size_pt=int(round(max(7.0, min(fit.used_font_size, 18.0)))),
                    block_id=block.block_id,
                    kind=block.block_type,
                )
            )
            if block.block_type == "caption":
                caption_annotation_count += 1
        else:
            item = _ReflowItem(
                source_block_id=block.block_id,
                source_page_num=block.page_num,
                kind=block.block_type,
                text=_normalize_text(block.text),
            )
            if block.block_type == "caption":
                caption_overflow.append(item)
            else:
                body_overflow.append(item)
            overflow_block_ids.add(block.block_id)
            warnings.append(f"block {block.block_id}: fitted text empty, moved to reflow")
            continue

        if fit.overflow_text.strip():
            overflow_item = _ReflowItem(
                source_block_id=block.block_id,
                source_page_num=block.page_num,
                kind=block.block_type,
                text=fit.overflow_text,
            )
            if block.block_type == "caption":
                caption_overflow.append(overflow_item)
            else:
                body_overflow.append(overflow_item)

            overflow_block_ids.add(block.block_id)
            multi_page_block_ids.add(block.block_id)

    footnote_annotations, footnote_overflow_items, page_footnote_warnings = _layout_page_footnotes(
        page_num=page.page_num,
        page_width=page.width,
        page_height=page.height,
        footnote_top=footnote_top,
        footnote_lines=footnote_lines,
        config=config,
    )
    annotations.extend(footnote_annotations)
    footnote_annotation_count += len(footnote_annotations)
    reflow_items.extend(footnote_overflow_items)
    footnote_overflow_count += len(footnote_overflow_items)
    warnings.extend(page_footnote_warnings)

    if page.image_items and caption_overflow:
        for image_row in page.image_items:
            image_id = str(image_row.get("image_id", "")).strip()
            if not image_id:
                continue
            reflow_items.append(
                _ReflowItem(
                    source_block_id=image_id,
                    source_page_num=page.page_num,
                    kind="image_ref",
                    text=f"[Изображение {image_id}]",
                )
            )

    reflow_items.extend(caption_overflow)
    reflow_items.extend(body_overflow)

    return _PageTypesetResult(
        annotations=annotations,
        reflow_items=reflow_items,
        warnings=warnings,
        widow_orphan_adjustments=widow_orphan_adjustments,
        footnote_annotation_count=footnote_annotation_count,
        caption_annotation_count=caption_annotation_count,
        overflow_block_ids=overflow_block_ids,
        multi_page_block_ids=multi_page_block_ids,
        footnote_overflow_count=footnote_overflow_count,
    )


def _collect_page_footnotes(*, page: ComposedPage, translated_blocks: list[ComposedTextBlock]) -> list[str]:
    rows: list[str] = []
    used_block_ids: set[str] = set()

    for block in translated_blocks:
        text = _normalize_text(block.text)
        if not text:
            continue
        used_block_ids.add(block.block_id)
        rows.append(text)

    for item in page.footnote_items:
        source_block_id = str(item.get("source_block_id", "")).strip()
        if source_block_id and source_block_id in used_block_ids:
            continue

        text = _normalize_text(str(item.get("text", "")))
        if not text:
            continue
        marker = str(item.get("marker", "")).strip()
        if marker:
            text = f"{marker} {text}"
        rows.append(text)

    return rows


def _reserved_footnote_height(*, page_height: float, footnote_line_count: int, config: TypesettingConfig) -> float:
    if config.footnote_area_policy == "ignore":
        return 0.0

    line_height = 9.0 * config.line_spacing
    dynamic_height = (footnote_line_count * line_height) + 6.0
    max_reserved = page_height * config.footnote_area_ratio

    if config.footnote_area_policy == "reserve":
        if footnote_line_count == 0:
            return max_reserved
        return min(max_reserved, max(32.0, dynamic_height))

    if footnote_line_count == 0:
        return 0.0
    return min(max_reserved, max(24.0, dynamic_height))


def _clip_rect_for_footnote_area(
    *,
    rect: tuple[float, float, float, float],
    block: ComposedTextBlock,
    footnote_top: float,
) -> tuple[float, float, float, float] | None:
    if block.block_type in {"footnote_body", "footnote_marker"}:
        return rect

    x0, y0, x1, y1 = rect
    y0 = max(y0, footnote_top)
    if y1 <= y0 + 2.0:
        return None
    return (x0, y0, x1, y1)


def _layout_page_footnotes(
    *,
    page_num: int,
    page_width: float,
    page_height: float,
    footnote_top: float,
    footnote_lines: list[str],
    config: TypesettingConfig,
) -> tuple[list[AnnotationSpec], list[_ReflowItem], list[str]]:
    annotations: list[AnnotationSpec] = []
    overflow_items: list[_ReflowItem] = []
    warnings: list[str] = []

    if not footnote_lines:
        return annotations, overflow_items, warnings

    if config.footnote_area_policy == "ignore":
        for index, text in enumerate(footnote_lines, start=1):
            overflow_items.append(
                _ReflowItem(
                    source_block_id=f"page-{page_num}-footnote-{index}",
                    source_page_num=page_num,
                    kind="footnote",
                    text=text,
                )
            )
        return annotations, overflow_items, warnings

    left = config.page_margins.left
    right = page_width - config.page_margins.right
    bottom = config.page_margins.bottom
    top = max(bottom + 2.0, footnote_top - 2.0)

    if right <= left or top <= bottom:
        for index, text in enumerate(footnote_lines, start=1):
            overflow_items.append(
                _ReflowItem(
                    source_block_id=f"page-{page_num}-footnote-{index}",
                    source_page_num=page_num,
                    kind="footnote",
                    text=text,
                )
            )
        warnings.append(f"page {page_num}: footnote area invalid, all footnotes moved to reflow")
        return annotations, overflow_items, warnings

    width = right - left
    height = top - bottom
    footnote_font = 9.0
    chars_per_line = max(18, int(width / (footnote_font * 0.52)))
    line_capacity = max(1, int(height / (footnote_font * config.line_spacing)))

    wrapped: list[str] = []
    for index, row in enumerate(footnote_lines, start=1):
        prefix = f"[{index}] "
        wrapped_rows = _wrap_text(row, width=max(10, chars_per_line - len(prefix)))
        if not wrapped_rows:
            continue
        wrapped.append(prefix + wrapped_rows[0])
        for tail in wrapped_rows[1:]:
            wrapped.append(" " * len(prefix) + tail)

    split_count, adjusted = _split_for_widow_orphan(
        total_lines=len(wrapped),
        line_capacity=line_capacity,
        widow_lines=1,
        orphan_lines=1,
    )
    if adjusted:
        warnings.append(f"page {page_num}: footnote widow/orphan adjustment applied")

    local_lines = wrapped[:split_count]
    overflow_lines = wrapped[split_count:]

    if local_lines:
        annotations.append(
            AnnotationSpec(
                page_num=page_num,
                rect=(left, bottom, right, top),
                text="\n".join(local_lines),
                font_size_pt=int(footnote_font),
                block_id=f"page-{page_num}-footnotes",
                kind="footnote_page",
            )
        )

    if overflow_lines:
        overflow_text = "\n".join(overflow_lines)
        overflow_items.append(
            _ReflowItem(
                source_block_id=f"page-{page_num}-footnotes-overflow",
                source_page_num=page_num,
                kind="footnote",
                text=overflow_text,
            )
        )
        warnings.append(f"page {page_num}: footnotes overflow moved to controlled reflow")

    return annotations, overflow_items, warnings


def _normalized_rect(
    bbox: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    x0, y0, x1, y1 = bbox
    x0 = max(0.0, min(x0, page_width))
    x1 = max(0.0, min(x1, page_width))
    y0 = max(0.0, min(y0, page_height))
    y1 = max(0.0, min(y1, page_height))

    if x1 <= x0 or y1 <= y0:
        return None

    inset = 1.5
    return (
        max(0.0, x0 + inset),
        max(0.0, y0 + inset),
        min(page_width, x1 - inset),
        min(page_height, y1 - inset),
    )


def _fit_text_into_rect(
    *,
    text: str,
    rect: tuple[float, float, float, float],
    base_font_size: float,
    config: TypesettingConfig,
) -> _FitResult:
    x0, y0, x1, y1 = rect
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)

    normalized = _normalize_text(text)
    if not normalized:
        return _FitResult(
            fitted_text="",
            overflow_text="",
            used_font_size=base_font_size,
            widow_orphan_adjusted=False,
        )

    base_size = max(8.0, min(base_font_size, 16.0))
    min_size = max(7.0, base_size * config.font_scale_min)
    max_size = max(min_size, base_size * config.font_scale_max)

    candidate_sizes: list[float]
    if config.fallback_mode == "aggressive_reflow":
        candidate_sizes = []
        size = max_size
        while size >= min_size:
            candidate_sizes.append(round(size, 3))
            size -= 0.5
        if min_size not in candidate_sizes:
            candidate_sizes.append(min_size)
    else:
        candidate_sizes = [max(min_size, min(base_size, max_size))]

    best: _FitResult | None = None
    best_overflow_len = 10**9

    for candidate_size in candidate_sizes:
        chars_per_line = max(12, int(width / (candidate_size * 0.52)))
        line_capacity = max(1, int(height / (candidate_size * config.line_spacing)))
        wrapped = _wrap_text(normalized, chars_per_line)

        split_count, adjusted = _split_for_widow_orphan(
            total_lines=len(wrapped),
            line_capacity=line_capacity,
            widow_lines=config.widow_lines,
            orphan_lines=config.orphan_lines,
        )

        fitted = "\n".join(wrapped[:split_count]).strip()
        overflow = "\n".join(wrapped[split_count:]).strip()

        overflow_len = len(overflow)
        result = _FitResult(
            fitted_text=fitted,
            overflow_text=overflow,
            used_font_size=candidate_size,
            widow_orphan_adjusted=adjusted,
        )

        if overflow_len < best_overflow_len:
            best = result
            best_overflow_len = overflow_len

        if overflow_len == 0:
            return result

    if best is None:
        return _FitResult(
            fitted_text="",
            overflow_text=normalized,
            used_font_size=base_size,
            widow_orphan_adjusted=False,
        )
    return best


def _split_for_widow_orphan(
    *,
    total_lines: int,
    line_capacity: int,
    widow_lines: int,
    orphan_lines: int,
) -> tuple[int, bool]:
    if total_lines <= line_capacity:
        return total_lines, False

    if line_capacity < orphan_lines:
        return 0, True

    split = line_capacity
    adjusted = False

    remaining = total_lines - split
    if remaining < widow_lines:
        split = total_lines - widow_lines
        adjusted = True

    if split < orphan_lines:
        if total_lines >= orphan_lines + widow_lines:
            split = orphan_lines
            adjusted = True
        else:
            return 0, True

    split = max(0, min(split, total_lines))
    if split == total_lines:
        split = max(0, total_lines - widow_lines)
        adjusted = True

    return split, adjusted


def _wrap_text(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        clean = paragraph.strip()
        if not clean:
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                clean,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return lines


def _build_reflow_pages(
    *,
    items: Iterable[_ReflowItem],
    config: TypesettingConfig,
) -> tuple[list[ReflowPageSpec], int, set[str], list[str], int]:
    page_breaks = 0
    multi_page_block_ids: set[str] = set()
    warnings: list[str] = []
    widow_orphan_adjustments = 0

    body_font = 10.0
    footnote_font = 9.0
    title_lines = 2

    body_width = _PAGE_WIDTH_PT - config.page_margins.left - config.page_margins.right
    body_chars = max(20, int(body_width / (body_font * 0.52)))
    footnote_chars = max(20, int(body_width / (footnote_font * 0.52)))

    def capacities(has_footnotes: bool) -> tuple[int, int]:
        usable_height = _PAGE_HEIGHT_PT - config.page_margins.top - config.page_margins.bottom
        usable_lines = max(10, int(usable_height / (body_font * config.line_spacing)))
        usable_lines = max(4, usable_lines - title_lines)

        if config.footnote_area_policy == "ignore":
            return usable_lines, 0

        reserved_lines = max(
            2, int((_PAGE_HEIGHT_PT * config.footnote_area_ratio) / (footnote_font * config.line_spacing))
        )
        if config.footnote_area_policy == "reserve":
            return max(3, usable_lines - reserved_lines), reserved_lines
        if has_footnotes:
            return max(3, usable_lines - reserved_lines), reserved_lines
        return usable_lines, reserved_lines

    pages: list[ReflowPageSpec] = []
    current_body: list[str] = []
    current_footnotes: list[str] = []
    current_chars = 0

    def flush_page() -> None:
        nonlocal current_body, current_footnotes, current_chars
        if not current_body and not current_footnotes:
            return
        pages.append(
            ReflowPageSpec(
                title=f"Controlled Reflow {len(pages) + 1}",
                body_lines=tuple(current_body),
                footnote_lines=tuple(current_footnotes),
            )
        )
        current_body = []
        current_footnotes = []
        current_chars = 0

    for item in items:
        text = _normalize_text(item.text)
        if not text:
            continue

        is_footnote = item.kind in {"footnote", "footnote_body", "footnote_marker"}
        wrap_width = footnote_chars if is_footnote else body_chars
        wrapped = _wrap_text(text, wrap_width)

        if not wrapped:
            continue

        consumed_lines_for_item = 0

        while wrapped:
            has_footnotes = len(current_footnotes) > 0 or is_footnote
            body_capacity, footnote_capacity = capacities(has_footnotes)

            if config.reflow_page_char_budget > 0 and current_chars >= config.reflow_page_char_budget:
                flush_page()
                page_breaks += 1
                continue

            if is_footnote and config.footnote_area_policy != "ignore":
                available = footnote_capacity - len(current_footnotes)
                if available <= 0:
                    flush_page()
                    page_breaks += 1
                    continue

                split, adjusted = _split_for_widow_orphan(
                    total_lines=len(wrapped),
                    line_capacity=available,
                    widow_lines=1,
                    orphan_lines=1,
                )
                if adjusted:
                    widow_orphan_adjustments += 1
                if split == 0:
                    if current_footnotes:
                        flush_page()
                        page_breaks += 1
                        continue
                    split = min(available, len(wrapped))

                chunk = wrapped[:split]
                current_footnotes.extend(chunk)
                current_chars += sum(len(line) for line in chunk)
                wrapped = wrapped[split:]
                consumed_lines_for_item += len(chunk)

                if wrapped:
                    multi_page_block_ids.add(item.source_block_id)
                    flush_page()
                    page_breaks += 1
                continue

            available = body_capacity - len(current_body)
            if available <= 0:
                flush_page()
                page_breaks += 1
                continue

            split, adjusted = _split_for_widow_orphan(
                total_lines=len(wrapped),
                line_capacity=available,
                widow_lines=config.widow_lines,
                orphan_lines=config.orphan_lines,
            )
            if adjusted:
                widow_orphan_adjustments += 1

            if split == 0:
                if current_body:
                    flush_page()
                    page_breaks += 1
                    continue
                split = min(available, len(wrapped))

            chunk = wrapped[:split]
            if consumed_lines_for_item > 0 and chunk:
                chunk = [f"(continue) {chunk[0]}", *chunk[1:]]

            current_body.extend(chunk)
            current_chars += sum(len(line) for line in chunk)
            wrapped = wrapped[split:]
            consumed_lines_for_item += len(chunk)

            if wrapped:
                multi_page_block_ids.add(item.source_block_id)
                flush_page()
                page_breaks += 1

    flush_page()

    if not pages:
        return [], page_breaks, multi_page_block_ids, warnings, widow_orphan_adjustments

    return pages, page_breaks, multi_page_block_ids, warnings, widow_orphan_adjustments


def _normalize_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    compact = "\n".join(line for line in lines if line)
    return compact.strip()
