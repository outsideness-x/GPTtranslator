"""Local PDF inspection utilities."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader


class PdfInspectionError(RuntimeError):
    """Raised when inspection cannot be performed reliably."""


@dataclass(slots=True)
class PageInspection:
    """Per-page inspection snapshot."""

    page_number: int
    width: float
    height: float
    has_text: bool
    text_char_count: int
    has_images: bool
    possible_footnotes_or_endnotes: bool
    possible_multi_column: bool
    header_candidate: str | None = None
    footer_candidate: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "has_text": self.has_text,
            "text_char_count": self.text_char_count,
            "has_images": self.has_images,
            "possible_footnotes_or_endnotes": self.possible_footnotes_or_endnotes,
            "possible_multi_column": self.possible_multi_column,
            "header_candidate": self.header_candidate,
            "footer_candidate": self.footer_candidate,
        }


@dataclass(slots=True)
class InspectionReport:
    """Top-level inspection report for one PDF."""

    source_pdf: str
    inspected_at: str
    page_count: int
    has_text_layer: bool
    likely_scan: bool
    has_images: bool
    possible_footnotes_or_endnotes: bool
    has_headers_or_footers: bool
    has_multi_column_pages: bool
    main_page_sizes: list[dict[str, Any]]
    pages: list[PageInspection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_pdf": self.source_pdf,
            "inspected_at": self.inspected_at,
            "page_count": self.page_count,
            "has_text_layer": self.has_text_layer,
            "likely_scan": self.likely_scan,
            "has_images": self.has_images,
            "possible_footnotes_or_endnotes": self.possible_footnotes_or_endnotes,
            "has_headers_or_footers": self.has_headers_or_footers,
            "has_multi_column_pages": self.has_multi_column_pages,
            "main_page_sizes": self.main_page_sizes,
            "pages": [page.to_dict() for page in self.pages],
            "warnings": self.warnings,
        }


_FOOTNOTE_RE = re.compile(r"^\s*(\[?\d{1,3}\]?|\d{1,3}[\.)])\s+\S+")
_MULTICOLUMN_RE = re.compile(r"\S.{0,50}\s{7,}\S")


def inspect_pdf(pdf_path: Path) -> InspectionReport:
    """Inspect a PDF using local heuristics only."""

    source_pdf = pdf_path.expanduser().resolve()
    if not source_pdf.exists() or not source_pdf.is_file():
        raise PdfInspectionError(f"PDF file not found: {source_pdf}")

    try:
        reader = PdfReader(str(source_pdf))
    except Exception as exc:  # pragma: no cover - backend-specific exceptions
        raise PdfInspectionError(f"Unable to open PDF: {source_pdf.name}") from exc

    page_count = len(reader.pages)
    if page_count == 0:
        raise PdfInspectionError("PDF contains zero pages.")

    size_counter: Counter[tuple[float, float]] = Counter()
    header_tokens: list[str] = []
    footer_tokens: list[str] = []
    pages: list[PageInspection] = []
    warnings: list[str] = []

    text_pages = 0
    image_pages = 0
    footnote_pages = 0
    multicolumn_pages = 0

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            size_counter[(round(width, 1), round(height, 1))] += 1

            layout_text = _extract_text(page, layout=True)
            plain_text = _extract_text(page, layout=False)
            best_text = layout_text if layout_text.strip() else plain_text

            lines = _clean_lines(best_text)
            char_count = _text_char_count(best_text)
            has_text = char_count > 0
            has_images = _page_has_images(page)
            has_footnotes = _has_possible_footnotes_or_endnotes(lines, best_text)
            has_multicolumn = _looks_multi_column(layout_text if layout_text else best_text)

            header_candidate = lines[0] if lines else None
            footer_candidate = lines[-1] if lines else None
            if header_candidate:
                token = _normalize_line_token(header_candidate)
                if token:
                    header_tokens.append(token)
            if footer_candidate:
                token = _normalize_line_token(footer_candidate)
                if token:
                    footer_tokens.append(token)

            if has_text:
                text_pages += 1
            if has_images:
                image_pages += 1
            if has_footnotes:
                footnote_pages += 1
            if has_multicolumn:
                multicolumn_pages += 1

            pages.append(
                PageInspection(
                    page_number=page_number,
                    width=width,
                    height=height,
                    has_text=has_text,
                    text_char_count=char_count,
                    has_images=has_images,
                    possible_footnotes_or_endnotes=has_footnotes,
                    possible_multi_column=has_multicolumn,
                    header_candidate=header_candidate,
                    footer_candidate=footer_candidate,
                )
            )
        except Exception as exc:  # pragma: no cover - corrupted page edge-case
            warnings.append(f"Page {page_number}: inspection failed ({exc})")

    if not pages:
        raise PdfInspectionError("Inspection failed for all pages.")

    has_text_layer = text_pages > 0
    has_images = image_pages > 0
    text_ratio = text_pages / page_count
    image_ratio = image_pages / page_count
    likely_scan = (not has_text_layer and has_images) or (text_ratio < 0.2 and image_ratio >= 0.5)

    has_headers_or_footers = _has_repeated_tokens(header_tokens, page_count) or _has_repeated_tokens(
        footer_tokens,
        page_count,
    )

    main_page_sizes = [
        {
            "width": width,
            "height": height,
            "count": count,
        }
        for (width, height), count in size_counter.most_common(5)
    ]

    return InspectionReport(
        source_pdf=str(source_pdf),
        inspected_at=datetime.now(timezone.utc).isoformat(),
        page_count=page_count,
        has_text_layer=has_text_layer,
        likely_scan=likely_scan,
        has_images=has_images,
        possible_footnotes_or_endnotes=footnote_pages > 0,
        has_headers_or_footers=has_headers_or_footers,
        has_multi_column_pages=multicolumn_pages > 0,
        main_page_sizes=main_page_sizes,
        pages=pages,
        warnings=warnings,
    )


def save_inspection_report(report_path: Path, report: InspectionReport) -> None:
    """Save inspection report to JSON file."""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _extract_text(page: Any, layout: bool) -> str:
    try:
        if layout:
            return str(page.extract_text(extraction_mode="layout") or "")
        return str(page.extract_text() or "")
    except TypeError:
        if layout:
            return str(page.extract_text() or "")
        return ""
    except Exception:
        return ""


def _clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _text_char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _has_possible_footnotes_or_endnotes(lines: list[str], text: str) -> bool:
    tail = lines[-8:] if len(lines) > 8 else lines
    for line in tail:
        if _FOOTNOTE_RE.match(line):
            return True

    lowered = text.lower()
    return "endnotes" in lowered or "footnotes" in lowered


def _looks_multi_column(text: str) -> bool:
    lines = _clean_lines(text)
    if not lines:
        return False

    spaced_lines = sum(1 for line in lines if _MULTICOLUMN_RE.search(line))
    return spaced_lines >= 3 or (spaced_lines >= 2 and spaced_lines / len(lines) >= 0.25)


def _normalize_line_token(line: str) -> str:
    cleaned = re.sub(r"\d+", "#", line.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or len(cleaned) < 3:
        return ""
    return cleaned


def _has_repeated_tokens(tokens: list[str], page_count: int) -> bool:
    if page_count < 2 or not tokens:
        return False

    counts = Counter(tokens)
    _, max_count = counts.most_common(1)[0]
    return max_count >= 2 and (max_count / page_count) >= 0.4


def _page_has_images(page: Any) -> bool:
    resources = _resolve_object(page.get("/Resources"))
    if not isinstance(resources, dict):
        return False
    return _xobject_has_images(resources.get("/XObject"), seen=set())


def _xobject_has_images(xobject_obj: Any, seen: set[int]) -> bool:
    xobjects = _resolve_object(xobject_obj)
    if not isinstance(xobjects, dict):
        return False

    for value in xobjects.values():
        obj = _resolve_object(value)
        obj_id = id(obj)
        if obj_id in seen:
            continue
        seen.add(obj_id)

        if not isinstance(obj, dict):
            continue

        subtype = str(obj.get("/Subtype", ""))
        if subtype == "/Image":
            return True

        if subtype == "/Form":
            resources = _resolve_object(obj.get("/Resources"))
            if isinstance(resources, dict) and _xobject_has_images(resources.get("/XObject"), seen):
                return True

    return False


def _resolve_object(value: Any) -> Any:
    try:
        return value.get_object()
    except AttributeError:
        return value
    except Exception:
        return value
