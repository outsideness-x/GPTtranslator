"""Local PDF extraction and structural document modeling."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from pypdf import PdfReader


class PdfExtractionError(RuntimeError):
    """Raised when extraction cannot produce reliable artifacts."""


@dataclass(slots=True)
class ExtractedBlock:
    """Structured block item for blocks.jsonl."""

    block_id: str
    page_num: int
    block_type: str
    bbox: tuple[float, float, float, float] | None
    reading_order: int
    text: str
    style_metadata: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "page_num": self.page_num,
            "block_type": self.block_type,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "reading_order": self.reading_order,
            "text": self.text,
            "style_metadata": self.style_metadata,
            "flags": self.flags,
        }


@dataclass(slots=True)
class ExtractedPage:
    """Page-level summary record for pages.jsonl."""

    page_num: int
    width: float
    height: float
    reading_order_strategy: str
    block_count: int
    image_count: int
    footnote_count: int
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_num": self.page_num,
            "width": self.width,
            "height": self.height,
            "reading_order_strategy": self.reading_order_strategy,
            "block_count": self.block_count,
            "image_count": self.image_count,
            "footnote_count": self.footnote_count,
            "flags": self.flags,
        }


@dataclass(slots=True)
class ExtractedImage:
    """Image metadata record for images.jsonl."""

    image_id: str
    page_num: int
    object_name: str
    width: int | None
    height: int | None
    color_space: str | None
    bits_per_component: int | None
    filters: list[str]
    anchor_block_id: str | None = None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "page_num": self.page_num,
            "object_name": self.object_name,
            "width": self.width,
            "height": self.height,
            "color_space": self.color_space,
            "bits_per_component": self.bits_per_component,
            "filters": self.filters,
            "anchor_block_id": self.anchor_block_id,
            "flags": self.flags,
        }


@dataclass(slots=True)
class ExtractedFootnote:
    """Footnote record for footnotes.jsonl."""

    footnote_id: str
    page_num: int
    kind: str
    marker: str | None
    text: str
    source_block_id: str
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "footnote_id": self.footnote_id,
            "page_num": self.page_num,
            "kind": self.kind,
            "marker": self.marker,
            "text": self.text,
            "source_block_id": self.source_block_id,
            "flags": self.flags,
        }


@dataclass(slots=True)
class ExtractionResult:
    """Container for extraction artifacts and summary metadata."""

    source_pdf: str
    extracted_at: str
    page_count: int
    pages: list[ExtractedPage]
    blocks: list[ExtractedBlock]
    images: list[ExtractedImage]
    footnotes: list[ExtractedFootnote]
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "source_pdf": self.source_pdf,
            "extracted_at": self.extracted_at,
            "page_count": self.page_count,
            "block_count": len(self.blocks),
            "image_count": len(self.images),
            "footnote_count": len(self.footnotes),
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class _TextSpan:
    text: str
    x: float
    y: float
    font_size: float
    font_name: str

    @property
    def estimated_width(self) -> float:
        text_len = max(len(self.text.strip()), 1)
        return max(text_len * self.font_size * 0.5, self.font_size)


@dataclass(slots=True)
class _LineCandidate:
    page_num: int
    text: str
    bbox: tuple[float, float, float, float] | None
    avg_font_size: float
    max_font_size: float
    font_names: list[str]
    flags: list[str]
    block_type: str = "paragraph"
    confidence: float = 0.8
    reading_order: int = 0
    block_id: str = ""
    style_metadata_extra: dict[str, Any] = field(default_factory=dict)


_FOOTNOTE_BODY_RE = re.compile(r"^\s*(\[?\d{1,3}\]?|\d{1,3}[\.)])\s+\S+")
_FOOTNOTE_MARKER_LINE_RE = re.compile(r"^\s*(\[\d{1,3}\]|\d{1,3})\s*$")
_FOOTNOTE_MARKER_INLINE_RE = re.compile(r"\[(\d{1,3})\]")
_CAPTION_RE = re.compile(r"^(figure|fig\.?|table|image|photo)\s*\d*\s*[:.\-)]\s+", re.IGNORECASE)


def extract_pdf_structure(pdf_path: Path) -> ExtractionResult:
    """Extract local structural representation from PDF."""

    source_pdf = pdf_path.expanduser().resolve()
    if not source_pdf.exists() or not source_pdf.is_file():
        raise PdfExtractionError(f"PDF file not found: {source_pdf}")

    try:
        reader = PdfReader(str(source_pdf))
    except Exception as exc:  # pragma: no cover - backend-specific exceptions
        raise PdfExtractionError(f"Unable to open PDF: {source_pdf.name}") from exc

    total_pages = len(reader.pages)
    if total_pages == 0:
        raise PdfExtractionError("PDF contains zero pages.")

    all_lines: list[_LineCandidate] = []
    pages: list[ExtractedPage] = []
    images: list[ExtractedImage] = []
    warnings: list[str] = []

    image_counter = 1

    for page_num, page in enumerate(reader.pages, start=1):
        try:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
        except Exception as exc:
            warnings.append(f"Page {page_num}: unable to read page size ({exc})")
            continue

        try:
            line_candidates = _extract_page_lines(page, page_num=page_num, width=width, height=height)
            reading_order_strategy = _assign_reading_order(line_candidates, page_width=width)
            _classify_page_blocks(line_candidates, page_height=height)

            page_images = _extract_page_images(page, page_num=page_num, start_index=image_counter)
            image_counter += len(page_images)
            images.extend(page_images)

            image_anchor_count = 0
            for image in page_images:
                image_anchor_count += 1
                line_candidates.append(
                    _LineCandidate(
                        page_num=page_num,
                        text=f"[IMAGE {image.image_id}]",
                        bbox=None,
                        avg_font_size=0.0,
                        max_font_size=0.0,
                        font_names=[],
                        flags=["low_confidence_bbox", "image_anchor"],
                        block_type="image_anchor",
                        confidence=0.45,
                        style_metadata_extra={
                            "image_id": image.image_id,
                            "image_width": image.width,
                            "image_height": image.height,
                            "image_color_space": image.color_space,
                        },
                    )
                )

            if image_anchor_count:
                _assign_reading_order(line_candidates, page_width=width)

            for idx, line in enumerate(sorted(line_candidates, key=lambda item: item.reading_order), start=1):
                line.block_id = f"blk-{page_num:04d}-{idx:04d}"

            page_footnotes = [line for line in line_candidates if line.block_type in {"footnote_body", "footnote_marker"}]
            pages.append(
                ExtractedPage(
                    page_num=page_num,
                    width=width,
                    height=height,
                    reading_order_strategy=reading_order_strategy,
                    block_count=len(line_candidates),
                    image_count=len(page_images),
                    footnote_count=len(page_footnotes),
                    flags=_page_flags(line_candidates, page_images),
                )
            )

            all_lines.extend(line_candidates)
        except Exception as exc:  # pragma: no cover - extraction should continue per page
            warnings.append(f"Page {page_num}: extraction failed ({exc})")

    if not pages:
        raise PdfExtractionError("Extraction failed for all pages.")

    _mark_headers_and_footers(all_lines, page_count=len(pages))

    blocks = [
        ExtractedBlock(
            block_id=line.block_id,
            page_num=line.page_num,
            block_type=line.block_type,
            bbox=line.bbox,
            reading_order=line.reading_order,
            text=line.text,
            style_metadata={
                "avg_font_size": line.avg_font_size,
                "max_font_size": line.max_font_size,
                "font_names": line.font_names,
                "confidence": round(line.confidence, 3),
                **line.style_metadata_extra,
            },
            flags=sorted(set(line.flags)),
        )
        for line in sorted(all_lines, key=lambda item: (item.page_num, item.reading_order))
    ]

    _attach_image_anchor_ids(images, blocks)
    footnotes = _collect_footnotes(blocks)

    return ExtractionResult(
        source_pdf=str(source_pdf),
        extracted_at=datetime.now(timezone.utc).isoformat(),
        page_count=len(pages),
        pages=sorted(pages, key=lambda item: item.page_num),
        blocks=blocks,
        images=images,
        footnotes=footnotes,
        warnings=warnings,
    )


def save_extraction_artifacts(analysis_dir: Path, result: ExtractionResult) -> dict[str, str]:
    """Persist extraction result into JSONL artifacts."""

    analysis_root = analysis_dir.resolve()
    analysis_root.mkdir(parents=True, exist_ok=True)

    pages_path = analysis_root / "pages.jsonl"
    blocks_path = analysis_root / "blocks.jsonl"
    images_path = analysis_root / "images.jsonl"
    footnotes_path = analysis_root / "footnotes.jsonl"

    _write_jsonl(pages_path, [item.to_dict() for item in result.pages])
    _write_jsonl(blocks_path, [item.to_dict() for item in result.blocks])
    _write_jsonl(images_path, [item.to_dict() for item in result.images])
    _write_jsonl(footnotes_path, [item.to_dict() for item in result.footnotes])

    return {
        "pages": str(pages_path),
        "blocks": str(blocks_path),
        "images": str(images_path),
        "footnotes": str(footnotes_path),
    }


def _extract_page_lines(page: Any, page_num: int, width: float, height: float) -> list[_LineCandidate]:
    spans = _extract_spans(page)
    if spans:
        lines = _build_lines_from_spans(spans=spans, page_num=page_num, page_width=width, page_height=height)
        return lines

    fallback_text = _extract_plain_text(page)
    lines = _build_lines_from_fallback_text(
        text=fallback_text,
        page_num=page_num,
        page_width=width,
        page_height=height,
    )
    return lines


def _extract_spans(page: Any) -> list[_TextSpan]:
    spans: list[_TextSpan] = []

    def visitor(text: str, _cm: Any, tm: Any, font_dict: Any, font_size: float) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        try:
            x = float(tm[4])
            y = float(tm[5])
        except Exception:
            return

        font_name = "unknown"
        if isinstance(font_dict, dict):
            font_name = str(font_dict.get("/BaseFont", "unknown"))

        spans.append(
            _TextSpan(
                text=cleaned,
                x=x,
                y=y,
                font_size=float(font_size) if font_size else 0.0,
                font_name=font_name,
            )
        )

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return []

    return spans


def _build_lines_from_spans(
    spans: list[_TextSpan],
    page_num: int,
    page_width: float,
    page_height: float,
) -> list[_LineCandidate]:
    groups: list[list[_TextSpan]] = []

    for span in sorted(spans, key=lambda item: (-item.y, item.x)):
        placed = False
        for group in groups:
            representative_y = group[0].y
            if abs(representative_y - span.y) <= 3.0:
                group.append(span)
                placed = True
                break
        if not placed:
            groups.append([span])

    lines: list[_LineCandidate] = []
    for group in groups:
        sorted_group = sorted(group, key=lambda item: item.x)
        text = " ".join(item.text for item in sorted_group).strip()
        if not text:
            continue

        x0 = max(0.0, min(item.x for item in sorted_group))
        y0 = max(0.0, min(item.y for item in sorted_group))
        x1 = min(page_width, max(item.x + item.estimated_width for item in sorted_group))
        y1 = min(page_height, max(item.y + max(item.font_size, 10.0) * 1.2 for item in sorted_group))

        font_sizes = [max(item.font_size, 0.0) for item in sorted_group if item.font_size > 0]
        avg_font = sum(font_sizes) / len(font_sizes) if font_sizes else 0.0
        max_font = max(font_sizes) if font_sizes else 0.0
        fonts = sorted(set(item.font_name for item in sorted_group if item.font_name))

        lines.append(
            _LineCandidate(
                page_num=page_num,
                text=text,
                bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                avg_font_size=round(avg_font, 2),
                max_font_size=round(max_font, 2),
                font_names=fonts,
                flags=[],
            )
        )

    return lines


def _build_lines_from_fallback_text(
    text: str,
    page_num: int,
    page_width: float,
    page_height: float,
) -> list[_LineCandidate]:
    lines_raw = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines_raw:
        return []

    line_step = page_height / max(len(lines_raw) + 1, 1)
    lines: list[_LineCandidate] = []

    for index, line in enumerate(lines_raw, start=1):
        top = page_height - (index * line_step)
        bottom = max(0.0, top - line_step * 0.8)
        width_est = min(page_width - 72.0, max(80.0, len(line) * 5.0))
        bbox = (72.0, round(bottom, 2), round(72.0 + width_est, 2), round(top, 2))
        lines.append(
            _LineCandidate(
                page_num=page_num,
                text=line,
                bbox=bbox,
                avg_font_size=10.0,
                max_font_size=10.0,
                font_names=[],
                flags=["fallback_text_extraction", "low_confidence_bbox"],
                confidence=0.45,
            )
        )

    return lines


def _extract_plain_text(page: Any) -> str:
    try:
        return str(page.extract_text(extraction_mode="layout") or "")
    except Exception:
        try:
            return str(page.extract_text() or "")
        except Exception:
            return ""


def _assign_reading_order(lines: list[_LineCandidate], page_width: float) -> str:
    if not lines:
        return "none"

    text_lines = [line for line in lines if line.block_type != "image_anchor" and line.bbox is not None]
    has_two_columns = _is_two_column_layout(text_lines, page_width)

    ordered: list[_LineCandidate]
    if has_two_columns:
        left = [line for line in lines if _bbox_center_x(line.bbox) < page_width * 0.5]
        right = [line for line in lines if _bbox_center_x(line.bbox) >= page_width * 0.5]
        ordered = _sort_lines_reading_flow(left) + _sort_lines_reading_flow(right)
        strategy = "two-column"
    else:
        ordered = _sort_lines_reading_flow(lines)
        strategy = "single-column"

    for order, line in enumerate(ordered, start=1):
        line.reading_order = order

    return strategy


def _sort_lines_reading_flow(lines: list[_LineCandidate]) -> list[_LineCandidate]:
    return sorted(
        lines,
        key=lambda item: (
            -(_bbox_y_top(item.bbox)),
            _bbox_x_left(item.bbox),
        ),
    )


def _is_two_column_layout(lines: list[_LineCandidate], page_width: float) -> bool:
    if len(lines) < 8:
        return False

    left = [line for line in lines if _bbox_center_x(line.bbox) < page_width * 0.48]
    right = [line for line in lines if _bbox_center_x(line.bbox) > page_width * 0.52]

    if len(left) < 3 or len(right) < 3:
        return False

    left_y = [_bbox_y_top(line.bbox) for line in left]
    right_y = [_bbox_y_top(line.bbox) for line in right]
    if not left_y or not right_y:
        return False

    overlap_top = min(max(left_y), max(right_y))
    overlap_bottom = max(min(left_y), min(right_y))
    return overlap_top > overlap_bottom


def _classify_page_blocks(lines: list[_LineCandidate], page_height: float) -> None:
    text_lines = [line for line in lines if line.block_type != "image_anchor"]
    font_candidates = [line.max_font_size for line in text_lines if line.max_font_size > 0]
    median_font = median(font_candidates) if font_candidates else 10.0

    for index, line in enumerate(_sort_lines_reading_flow(text_lines)):
        block_type, confidence, extra_flags = _classify_line(
            text=line.text,
            bbox=line.bbox,
            max_font_size=line.max_font_size,
            median_font_size=median_font,
            page_height=page_height,
            line_index=index,
        )
        line.block_type = block_type
        line.confidence = confidence
        line.flags.extend(extra_flags)


def _classify_line(
    text: str,
    bbox: tuple[float, float, float, float] | None,
    max_font_size: float,
    median_font_size: float,
    page_height: float,
    line_index: int,
) -> tuple[str, float, list[str]]:
    flags: list[str] = []
    normalized = text.strip()

    if _FOOTNOTE_MARKER_LINE_RE.match(normalized):
        return "footnote_marker", 0.55, ["low_confidence_block_type"]

    if bbox is not None and bbox[1] <= page_height * 0.22 and _FOOTNOTE_BODY_RE.match(normalized):
        return "footnote_body", 0.8, flags

    if _CAPTION_RE.match(normalized):
        return "caption", 0.85, flags

    heading_by_size = bool(median_font_size and max_font_size >= median_font_size * 1.25 and len(normalized) <= 120)
    heading_by_position = line_index <= 1 and len(normalized) <= 80 and normalized == normalized.title()

    if heading_by_size:
        return "heading", 0.88, flags

    if heading_by_position:
        flags.append("low_confidence_block_type")
        return "heading", 0.6, flags

    if len(normalized) < 5:
        flags.append("low_confidence_block_type")
        return "paragraph", 0.55, flags

    if _FOOTNOTE_MARKER_INLINE_RE.search(normalized):
        flags.append("possible_footnote_marker")

    return "paragraph", 0.78, flags


def _mark_headers_and_footers(lines: list[_LineCandidate], page_count: int) -> None:
    by_page: dict[int, list[_LineCandidate]] = defaultdict(list)
    for line in lines:
        if line.bbox is None or line.block_type == "image_anchor":
            continue
        by_page[line.page_num].append(line)

    top_tokens: Counter[str] = Counter()
    bottom_tokens: Counter[str] = Counter()

    top_line_refs: list[_LineCandidate] = []
    bottom_line_refs: list[_LineCandidate] = []

    for page_lines in by_page.values():
        ordered = _sort_lines_reading_flow(page_lines)
        if not ordered:
            continue

        top = ordered[0]
        bottom = sorted(page_lines, key=lambda line: _bbox_y_bottom(line.bbox))[0]

        top_line_refs.append(top)
        bottom_line_refs.append(bottom)

        top_token = _normalize_token(top.text)
        bottom_token = _normalize_token(bottom.text)
        if top_token:
            top_tokens[top_token] += 1
        if bottom_token:
            bottom_tokens[bottom_token] += 1

    repeated_top = {
        token for token, count in top_tokens.items() if count >= 2 and (count / max(page_count, 1)) >= 0.4
    }
    repeated_bottom = {
        token for token, count in bottom_tokens.items() if count >= 2 and (count / max(page_count, 1)) >= 0.4
    }

    for line in top_line_refs:
        if _normalize_token(line.text) in repeated_top:
            line.block_type = "header"
            line.confidence = min(1.0, max(line.confidence, 0.82))
            line.flags.append("heuristic_header_footer")

    for line in bottom_line_refs:
        if _normalize_token(line.text) in repeated_bottom:
            line.block_type = "footer"
            line.confidence = min(1.0, max(line.confidence, 0.82))
            line.flags.append("heuristic_header_footer")


def _extract_page_images(page: Any, page_num: int, start_index: int) -> list[ExtractedImage]:
    resources = _resolve_object(page.get("/Resources"))
    if not isinstance(resources, dict):
        return []

    images_raw = _collect_images_from_xobject(resources.get("/XObject"), name_prefix="", seen=set())
    result: list[ExtractedImage] = []

    for offset, image_data in enumerate(images_raw, start=0):
        image_id = f"img-{page_num:04d}-{start_index + offset:03d}"
        result.append(
            ExtractedImage(
                image_id=image_id,
                page_num=page_num,
                object_name=image_data.get("object_name", "unknown"),
                width=image_data.get("width"),
                height=image_data.get("height"),
                color_space=image_data.get("color_space"),
                bits_per_component=image_data.get("bits_per_component"),
                filters=image_data.get("filters", []),
                flags=["position_not_available"],
            )
        )

    return result


def _collect_images_from_xobject(xobject_obj: Any, name_prefix: str, seen: set[int]) -> list[dict[str, Any]]:
    xobjects = _resolve_object(xobject_obj)
    if not isinstance(xobjects, dict):
        return []

    images: list[dict[str, Any]] = []
    for key, value in xobjects.items():
        obj = _resolve_object(value)
        obj_id = id(obj)
        if obj_id in seen:
            continue
        seen.add(obj_id)

        if not isinstance(obj, dict):
            continue

        name = f"{name_prefix}/{key}" if name_prefix else str(key)
        subtype = str(obj.get("/Subtype", ""))

        if subtype == "/Image":
            filters_raw = _resolve_object(obj.get("/Filter"))
            filters: list[str]
            if isinstance(filters_raw, list):
                filters = [str(item) for item in filters_raw]
            elif filters_raw is None:
                filters = []
            else:
                filters = [str(filters_raw)]

            images.append(
                {
                    "object_name": name,
                    "width": _as_int(obj.get("/Width")),
                    "height": _as_int(obj.get("/Height")),
                    "color_space": str(obj.get("/ColorSpace")) if obj.get("/ColorSpace") is not None else None,
                    "bits_per_component": _as_int(obj.get("/BitsPerComponent")),
                    "filters": filters,
                }
            )
            continue

        if subtype == "/Form":
            form_resources = _resolve_object(obj.get("/Resources"))
            if isinstance(form_resources, dict):
                images.extend(
                    _collect_images_from_xobject(
                        form_resources.get("/XObject"),
                        name_prefix=name,
                        seen=seen,
                    )
                )

    return images


def _attach_image_anchor_ids(images: list[ExtractedImage], blocks: list[ExtractedBlock]) -> None:
    by_page: dict[int, list[ExtractedBlock]] = defaultdict(list)
    for block in blocks:
        if block.block_type == "image_anchor":
            by_page[block.page_num].append(block)

    for image in images:
        anchors = by_page.get(image.page_num, [])
        if not anchors:
            continue

        matched = next(
            (
                anchor
                for anchor in anchors
                if isinstance(anchor.style_metadata.get("image_id"), str)
                and anchor.style_metadata.get("image_id") == image.image_id
            ),
            None,
        )

        if matched is None:
            matched = next((anchor for anchor in anchors if image.image_id in anchor.text), anchors[0])

        image.anchor_block_id = matched.block_id


def _collect_footnotes(blocks: list[ExtractedBlock]) -> list[ExtractedFootnote]:
    footnotes: list[ExtractedFootnote] = []
    counter = 1

    for block in blocks:
        if block.block_type == "footnote_body":
            marker_match = _FOOTNOTE_BODY_RE.match(block.text)
            marker = marker_match.group(1) if marker_match else None
            footnotes.append(
                ExtractedFootnote(
                    footnote_id=f"fn-{counter:04d}",
                    page_num=block.page_num,
                    kind="body",
                    marker=marker,
                    text=block.text,
                    source_block_id=block.block_id,
                    flags=list(block.flags),
                )
            )
            counter += 1
            continue

        marker_matches = _FOOTNOTE_MARKER_INLINE_RE.findall(block.text)
        for marker in marker_matches:
            footnotes.append(
                ExtractedFootnote(
                    footnote_id=f"fn-{counter:04d}",
                    page_num=block.page_num,
                    kind="marker",
                    marker=marker,
                    text=block.text,
                    source_block_id=block.block_id,
                    flags=list(block.flags),
                )
            )
            counter += 1

        if block.block_type == "footnote_marker" and block.text.strip():
            footnotes.append(
                ExtractedFootnote(
                    footnote_id=f"fn-{counter:04d}",
                    page_num=block.page_num,
                    kind="marker",
                    marker=block.text.strip(),
                    text=block.text,
                    source_block_id=block.block_id,
                    flags=list(block.flags),
                )
            )
            counter += 1

    return footnotes


def _page_flags(lines: list[_LineCandidate], page_images: list[ExtractedImage]) -> list[str]:
    flags: list[str] = []
    if not any(line.text.strip() for line in lines if line.block_type != "image_anchor"):
        flags.append("no_text_detected")
    if page_images:
        flags.append("contains_images")
    if any("fallback_text_extraction" in line.flags for line in lines):
        flags.append("fallback_text_extraction")
    return flags


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _bbox_center_x(bbox: tuple[float, float, float, float] | None) -> float:
    if bbox is None:
        return float("inf")
    return (bbox[0] + bbox[2]) / 2.0


def _bbox_x_left(bbox: tuple[float, float, float, float] | None) -> float:
    if bbox is None:
        return float("inf")
    return bbox[0]


def _bbox_y_top(bbox: tuple[float, float, float, float] | None) -> float:
    if bbox is None:
        return float("-inf")
    return bbox[3]


def _bbox_y_bottom(bbox: tuple[float, float, float, float] | None) -> float:
    if bbox is None:
        return float("inf")
    return bbox[1]


def _normalize_token(text: str) -> str:
    cleaned = re.sub(r"\d+", "#", text.strip().lower())
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _resolve_object(value: Any) -> Any:
    try:
        return value.get_object()
    except AttributeError:
        return value
    except Exception:
        return value


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None
