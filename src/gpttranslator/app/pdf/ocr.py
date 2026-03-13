"""Optional local OCR branch for scanned PDFs."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .extractor import ExtractedBlock, ExtractedFootnote, ExtractedImage, ExtractedPage, ExtractionResult


class OcrError(RuntimeError):
    """Raised when OCR branch cannot be initialized."""


@dataclass(frozen=True, slots=True)
class OcrSettings:
    """Settings for local OCR pipeline."""

    language: str = "eng"
    dpi: int = 200
    block_low_confidence_threshold: float = 0.65
    page_low_confidence_threshold: float = 0.6


@dataclass(frozen=True, slots=True)
class OcrPageRecord:
    """Per-page OCR record stored as analysis/ocr_pages.jsonl row."""

    page_num: int
    width: float
    height: float
    image_path: str
    text_char_count: int
    block_count: int
    confidence: float
    low_confidence: bool
    flags: tuple[str, ...] = tuple()

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_num": self.page_num,
            "width": self.width,
            "height": self.height,
            "image_path": self.image_path,
            "text_char_count": self.text_char_count,
            "block_count": self.block_count,
            "confidence": round(self.confidence, 4),
            "low_confidence": self.low_confidence,
            "flags": list(self.flags),
        }


@dataclass(frozen=True, slots=True)
class OcrBlockRecord:
    """Per-block OCR record stored as analysis/ocr_blocks.jsonl row."""

    block_id: str
    page_num: int
    reading_order: int
    block_type: str
    text: str
    bbox: tuple[float, float, float, float] | None
    confidence: float
    low_confidence: bool
    flags: tuple[str, ...] = tuple()

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "page_num": self.page_num,
            "reading_order": self.reading_order,
            "block_type": self.block_type,
            "text": self.text,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "confidence": round(self.confidence, 4),
            "low_confidence": self.low_confidence,
            "flags": list(self.flags),
        }


@dataclass(frozen=True, slots=True)
class OcrBranchResult:
    """OCR branch output used by extraction command."""

    extraction_result: ExtractionResult
    ocr_pages: tuple[OcrPageRecord, ...]
    ocr_blocks: tuple[OcrBlockRecord, ...]
    warnings: tuple[str, ...] = tuple()

    @property
    def low_confidence_page_count(self) -> int:
        return sum(1 for item in self.ocr_pages if item.low_confidence)

    @property
    def low_confidence_block_count(self) -> int:
        return sum(1 for item in self.ocr_blocks if item.low_confidence)


def run_ocr_extraction(
    *,
    pdf_path: Path,
    analysis_dir: Path,
    settings: OcrSettings | None = None,
) -> OcrBranchResult:
    """Run local OCR branch and return pseudo-layout extraction output."""

    source_pdf = pdf_path.expanduser().resolve()
    if not source_pdf.exists() or not source_pdf.is_file():
        raise OcrError(f"PDF file not found: {source_pdf}")

    cfg = settings or OcrSettings()
    if cfg.dpi < 72:
        raise OcrError("OCR dpi must be >= 72")

    try:
        reader = PdfReader(str(source_pdf))
    except Exception as exc:  # pragma: no cover - backend specific
        raise OcrError(f"Unable to open PDF for OCR: {source_pdf.name}") from exc

    if len(reader.pages) == 0:
        raise OcrError("PDF contains zero pages.")

    ocr_images_dir = analysis_dir / "ocr_page_images"
    ocr_images_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []

    rendered_paths = _render_pdf_pages(pdf_path=source_pdf, images_dir=ocr_images_dir, dpi=cfg.dpi)
    if not rendered_paths:
        warnings.append("OCR renderer unavailable: page rasterization failed; falling back to plain text extraction")

    tesseract_available = shutil.which("tesseract") is not None
    if not tesseract_available:
        warnings.append("tesseract binary not found in PATH; using plain text fallback with low confidence")

    extracted_pages: list[ExtractedPage] = []
    extracted_blocks: list[ExtractedBlock] = []
    extracted_images: list[ExtractedImage] = []
    extracted_footnotes: list[ExtractedFootnote] = []

    ocr_page_rows: list[OcrPageRecord] = []
    ocr_block_rows: list[OcrBlockRecord] = []

    global_block_counter = 1
    global_footnote_counter = 1

    for page_num, page in enumerate(reader.pages, start=1):
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        page_image = rendered_paths.get(page_num)

        page_flags: list[str] = []
        if page_image is None:
            page_flags.append("ocr_page_image_missing")

        page_blocks, page_ocr_rows, page_warnings = _extract_page_ocr_blocks(
            page=page,
            page_num=page_num,
            page_width=page_width,
            page_height=page_height,
            page_image=page_image,
            tesseract_available=tesseract_available,
            settings=cfg,
        )
        warnings.extend(page_warnings)

        if not page_blocks:
            fallback_text = f"[OCR unresolved on page {page_num}]"
            block_id = f"ocr-blk-{page_num:04d}-{global_block_counter:04d}"
            global_block_counter += 1
            page_blocks = [
                ExtractedBlock(
                    block_id=block_id,
                    page_num=page_num,
                    block_type="paragraph",
                    bbox=(36.0, 72.0, max(100.0, page_width - 36.0), max(120.0, page_height - 72.0)),
                    reading_order=1,
                    text=fallback_text,
                    style_metadata={"ocr_confidence": 0.01, "ocr_fallback": True},
                    flags=["low_confidence_ocr", "ocr_unresolved_page"],
                )
            ]
            page_ocr_rows = [
                OcrBlockRecord(
                    block_id=block_id,
                    page_num=page_num,
                    reading_order=1,
                    block_type="paragraph",
                    text=fallback_text,
                    bbox=(36.0, 72.0, max(100.0, page_width - 36.0), max(120.0, page_height - 72.0)),
                    confidence=0.01,
                    low_confidence=True,
                    flags=("low_confidence_ocr", "ocr_unresolved_page"),
                )
            ]
            page_flags.append("ocr_unresolved_page")

        # Re-index block ids globally to avoid collisions across pages and keep deterministic ordering.
        reindexed_page_blocks: list[ExtractedBlock] = []
        remapped_ids: dict[str, str] = {}
        for block in sorted(page_blocks, key=lambda item: item.reading_order):
            new_block_id = f"ocr-blk-{page_num:04d}-{global_block_counter:04d}"
            remapped_ids[block.block_id] = new_block_id
            global_block_counter += 1
            reindexed_page_blocks.append(
                ExtractedBlock(
                    block_id=new_block_id,
                    page_num=block.page_num,
                    block_type=block.block_type,
                    bbox=block.bbox,
                    reading_order=block.reading_order,
                    text=block.text,
                    style_metadata=dict(block.style_metadata),
                    flags=list(block.flags),
                )
            )

        for row in page_ocr_rows:
            mapped_id = remapped_ids.get(row.block_id, row.block_id)
            ocr_block_rows.append(
                OcrBlockRecord(
                    block_id=mapped_id,
                    page_num=row.page_num,
                    reading_order=row.reading_order,
                    block_type=row.block_type,
                    text=row.text,
                    bbox=row.bbox,
                    confidence=row.confidence,
                    low_confidence=row.low_confidence,
                    flags=row.flags,
                )
            )

        page_blocks = reindexed_page_blocks
        extracted_blocks.extend(page_blocks)

        footnotes, next_counter = _collect_ocr_footnotes(
            blocks=page_blocks,
            start_counter=global_footnote_counter,
        )
        global_footnote_counter = next_counter
        extracted_footnotes.extend(footnotes)

        page_confidence = _mean([float(block.style_metadata.get("ocr_confidence", 0.0)) for block in page_blocks])
        low_conf_page = page_confidence < cfg.page_low_confidence_threshold
        if low_conf_page:
            page_flags.append("low_confidence_ocr_page")

        if page_image is not None:
            extracted_images.append(
                ExtractedImage(
                    image_id=f"ocr-page-{page_num:04d}",
                    page_num=page_num,
                    object_name=page_image.name,
                    width=None,
                    height=None,
                    color_space=None,
                    bits_per_component=None,
                    filters=[],
                    anchor_block_id=None,
                    flags=["ocr_page_raster", "non_pdf_xobject"],
                )
            )

        extracted_pages.append(
            ExtractedPage(
                page_num=page_num,
                width=page_width,
                height=page_height,
                reading_order_strategy="ocr_line_top_to_bottom",
                block_count=len(page_blocks),
                image_count=1 if page_image is not None else 0,
                footnote_count=len(
                    [block for block in page_blocks if block.block_type in {"footnote_body", "footnote_marker"}]
                ),
                flags=sorted(set(page_flags)),
            )
        )

        ocr_page_rows.append(
            OcrPageRecord(
                page_num=page_num,
                width=page_width,
                height=page_height,
                image_path=str(page_image) if page_image is not None else "",
                text_char_count=sum(len(_normalize_text(block.text).replace(" ", "")) for block in page_blocks),
                block_count=len(page_blocks),
                confidence=max(0.0, min(1.0, page_confidence)),
                low_confidence=low_conf_page,
                flags=tuple(sorted(set(page_flags))),
            )
        )

    extraction_result = ExtractionResult(
        source_pdf=str(source_pdf),
        extracted_at=datetime.now(timezone.utc).isoformat(),
        page_count=len(extracted_pages),
        pages=extracted_pages,
        blocks=sorted(extracted_blocks, key=lambda item: (item.page_num, item.reading_order, item.block_id)),
        images=extracted_images,
        footnotes=extracted_footnotes,
        warnings=warnings,
    )

    return OcrBranchResult(
        extraction_result=extraction_result,
        ocr_pages=tuple(ocr_page_rows),
        ocr_blocks=tuple(ocr_block_rows),
        warnings=tuple(warnings),
    )


def save_ocr_artifacts(analysis_dir: Path, result: OcrBranchResult) -> dict[str, str]:
    """Persist OCR branch artifacts as JSONL files."""

    root = analysis_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)

    ocr_pages_path = root / "ocr_pages.jsonl"
    ocr_blocks_path = root / "ocr_blocks.jsonl"

    with ocr_pages_path.open("w", encoding="utf-8") as file:
        for row in result.ocr_pages:
            file.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")

    with ocr_blocks_path.open("w", encoding="utf-8") as file:
        for block_row in result.ocr_blocks:
            file.write(json.dumps(block_row.to_dict(), ensure_ascii=False) + "\n")

    return {
        "ocr_pages": str(ocr_pages_path),
        "ocr_blocks": str(ocr_blocks_path),
    }


def _render_pdf_pages(*, pdf_path: Path, images_dir: Path, dpi: int) -> dict[int, Path]:
    renderer = shutil.which("pdftoppm")
    if renderer is None:
        return {}

    prefix = images_dir / "page"
    command = [
        renderer,
        "-r",
        str(dpi),
        "-png",
        str(pdf_path),
        str(prefix),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {}

    if completed.returncode != 0:
        return {}

    mapping: dict[int, Path] = {}
    for path in sorted(images_dir.glob("page-*.png")):
        match = re.search(r"(\d+)$", path.stem)
        if not match:
            continue
        page_num = int(match.group(1))
        mapping[page_num] = path
    return mapping


def _extract_page_ocr_blocks(
    *,
    page: Any,
    page_num: int,
    page_width: float,
    page_height: float,
    page_image: Path | None,
    tesseract_available: bool,
    settings: OcrSettings,
) -> tuple[list[ExtractedBlock], list[OcrBlockRecord], list[str]]:
    warnings: list[str] = []

    if page_image is not None and tesseract_available:
        tsv_text = _run_tesseract_tsv(image_path=page_image, language=settings.language, dpi=settings.dpi)
        if tsv_text is not None:
            parsed_blocks, parsed_rows = _parse_tesseract_tsv_to_blocks(
                tsv_text=tsv_text,
                page_num=page_num,
                page_width=page_width,
                page_height=page_height,
                low_conf_threshold=settings.block_low_confidence_threshold,
            )
            if parsed_blocks:
                return parsed_blocks, parsed_rows, warnings
            warnings.append(f"page {page_num}: OCR returned no text lines; plain text fallback used")
        else:
            warnings.append(f"page {page_num}: tesseract failed; plain text fallback used")

    fallback_text = _extract_plain_text(page)
    fallback_conf = 0.25 if fallback_text.strip() else 0.05
    if not fallback_text.strip():
        fallback_text = f"[OCR low-confidence placeholder on page {page_num}]"

    flags = ["ocr_plain_text_fallback", "low_confidence_ocr"]
    block_type = _classify_ocr_block_type(text=fallback_text, y0=72.0, y1=page_height - 72.0, page_height=page_height)
    block = ExtractedBlock(
        block_id=f"fallback-{page_num:04d}-0001",
        page_num=page_num,
        block_type=block_type,
        bbox=(36.0, 72.0, max(100.0, page_width - 36.0), max(120.0, page_height - 72.0)),
        reading_order=1,
        text=fallback_text,
        style_metadata={
            "avg_font_size": 10.0,
            "max_font_size": 10.0,
            "font_names": [],
            "confidence": round(fallback_conf, 3),
            "ocr_confidence": round(fallback_conf, 3),
            "ocr_engine": "fallback_plain_text",
        },
        flags=flags,
    )

    row = OcrBlockRecord(
        block_id=block.block_id,
        page_num=page_num,
        reading_order=1,
        block_type=block_type,
        text=fallback_text,
        bbox=block.bbox,
        confidence=fallback_conf,
        low_confidence=True,
        flags=tuple(flags),
    )

    return [block], [row], warnings


def _run_tesseract_tsv(*, image_path: Path, language: str, dpi: int) -> str | None:
    command = [
        "tesseract",
        str(image_path),
        "stdout",
        "-l",
        language,
        "--dpi",
        str(dpi),
        "tsv",
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    if completed.returncode != 0:
        return None

    return completed.stdout


def _parse_tesseract_tsv_to_blocks(
    *,
    tsv_text: str,
    page_num: int,
    page_width: float,
    page_height: float,
    low_conf_threshold: float,
) -> tuple[list[ExtractedBlock], list[OcrBlockRecord]]:
    lines = tsv_text.splitlines()
    if len(lines) < 2:
        return [], []

    image_width = 0.0
    image_height = 0.0

    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}

    for raw_line in lines[1:]:
        if not raw_line.strip():
            continue
        cols = raw_line.split("\t", 11)
        if len(cols) < 12:
            continue

        try:
            level = int(cols[0])
            block_num = int(cols[2])
            par_num = int(cols[3])
            line_num = int(cols[4])
            left = int(cols[6])
            top = int(cols[7])
            width = int(cols[8])
            height = int(cols[9])
            conf_raw = float(cols[10])
            text = cols[11].strip()
        except ValueError:
            continue

        if level == 1:
            image_width = max(image_width, float(width))
            image_height = max(image_height, float(height))
            continue

        if level != 5 or not text:
            continue

        if conf_raw < 0:
            conf_raw = 0.0

        key = (block_num, par_num, line_num)
        grouped.setdefault(key, []).append(
            {
                "text": text,
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
                "conf": conf_raw,
            }
        )

    if not grouped:
        return [], []

    if image_width <= 0 or image_height <= 0:
        max_right = max(max(item["right"] for item in words) for words in grouped.values())
        max_bottom = max(max(item["bottom"] for item in words) for words in grouped.values())
        image_width = float(max_right) if max_right > 0 else page_width
        image_height = float(max_bottom) if max_bottom > 0 else page_height

    line_items: list[tuple[int, float, float, list[dict[str, Any]]]] = []
    for idx, words in enumerate(grouped.values(), start=1):
        y_top = min(item["top"] for item in words)
        x_left = min(item["left"] for item in words)
        line_items.append((idx, float(y_top), float(x_left), words))

    line_items.sort(key=lambda item: (item[1], item[2]))

    extracted_blocks: list[ExtractedBlock] = []
    block_rows: list[OcrBlockRecord] = []

    for reading_order, (_, _, _, words) in enumerate(line_items, start=1):
        sorted_words = sorted(words, key=lambda item: item["left"])
        text = " ".join(item["text"] for item in sorted_words).strip()
        if not text:
            continue

        left = min(item["left"] for item in sorted_words)
        top = min(item["top"] for item in sorted_words)
        right = max(item["right"] for item in sorted_words)
        bottom = max(item["bottom"] for item in sorted_words)

        x0 = _scale(left, image_width, page_width)
        x1 = _scale(right, image_width, page_width)
        y1 = page_height - _scale(top, image_height, page_height)
        y0 = page_height - _scale(bottom, image_height, page_height)

        if x1 <= x0:
            x1 = min(page_width, x0 + 6.0)
        if y1 <= y0:
            y1 = min(page_height, y0 + 6.0)

        conf = _mean([float(item["conf"]) for item in sorted_words]) / 100.0
        conf = max(0.0, min(1.0, conf))
        low_confidence = conf < low_conf_threshold

        block_type = _classify_ocr_block_type(text=text, y0=y0, y1=y1, page_height=page_height)
        flags: list[str] = []
        if low_confidence:
            flags.append("low_confidence_ocr")

        block_id = f"line-{page_num:04d}-{reading_order:04d}"
        extracted_blocks.append(
            ExtractedBlock(
                block_id=block_id,
                page_num=page_num,
                block_type=block_type,
                bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                reading_order=reading_order,
                text=text,
                style_metadata={
                    "avg_font_size": 10.0,
                    "max_font_size": 10.0,
                    "font_names": ["OCR"],
                    "confidence": round(conf, 3),
                    "ocr_confidence": round(conf, 3),
                    "ocr_engine": "tesseract",
                },
                flags=flags,
            )
        )

        block_rows.append(
            OcrBlockRecord(
                block_id=block_id,
                page_num=page_num,
                reading_order=reading_order,
                block_type=block_type,
                text=text,
                bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                confidence=conf,
                low_confidence=low_confidence,
                flags=tuple(flags),
            )
        )

    return extracted_blocks, block_rows


def _classify_ocr_block_type(*, text: str, y0: float, y1: float, page_height: float) -> str:
    normalized = text.strip()
    if not normalized:
        return "paragraph"

    if _CAPTION_RE.match(normalized):
        return "caption"

    if y0 <= page_height * 0.22 and _FOOTNOTE_RE.match(normalized):
        return "footnote_body"

    if y1 >= page_height * 0.84 and len(normalized) <= 100:
        return "heading"

    return "paragraph"


def _collect_ocr_footnotes(
    *,
    blocks: list[ExtractedBlock],
    start_counter: int,
) -> tuple[list[ExtractedFootnote], int]:
    counter = start_counter
    footnotes: list[ExtractedFootnote] = []

    for block in blocks:
        if block.block_type == "footnote_body":
            marker_match = _FOOTNOTE_RE.match(block.text)
            marker = marker_match.group(1) if marker_match else None
            footnotes.append(
                ExtractedFootnote(
                    footnote_id=f"ocr-fn-{counter:04d}",
                    page_num=block.page_num,
                    kind="body",
                    marker=marker,
                    text=block.text,
                    source_block_id=block.block_id,
                    flags=list(block.flags),
                )
            )
            counter += 1

        for marker in _INLINE_MARKER_RE.findall(block.text):
            footnotes.append(
                ExtractedFootnote(
                    footnote_id=f"ocr-fn-{counter:04d}",
                    page_num=block.page_num,
                    kind="marker",
                    marker=marker,
                    text=block.text,
                    source_block_id=block.block_id,
                    flags=list(block.flags),
                )
            )
            counter += 1

    return footnotes, counter


def _extract_plain_text(page: Any) -> str:
    try:
        text = str(page.extract_text(extraction_mode="layout") or "")
        if text.strip():
            return text
    except Exception:
        pass

    try:
        return str(page.extract_text() or "")
    except Exception:
        return ""


def _scale(value: float, source_max: float, target_max: float) -> float:
    if source_max <= 0:
        return value
    return (value / source_max) * target_max


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _normalize_text(value: str) -> str:
    compact = re.sub(r"\s+", " ", value.strip())
    return compact


_CAPTION_RE = re.compile(r"^(figure|fig\.?|table|image|photo)\s*\d*\s*[:.\-)]\s+", re.IGNORECASE)
_FOOTNOTE_RE = re.compile(r"^\s*(\[?\d{1,3}\]?|\d{1,3}[\.)])\s+\S+")
_INLINE_MARKER_RE = re.compile(r"\[(\d{1,3})\]")
