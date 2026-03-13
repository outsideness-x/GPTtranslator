"""Build composition stage: map translated chunks onto document graph blocks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.models import Block, Chunk, PageInfo

TEXT_BLOCK_TYPES: frozenset[str] = frozenset(
    {
        "paragraph",
        "heading",
        "caption",
        "footnote_body",
        "footnote_marker",
    }
)


@dataclass(frozen=True, slots=True)
class ComposedTextBlock:
    """Translated text bound to one source block."""

    block_id: str
    chunk_id: str
    page_num: int
    block_type: str
    text: str
    bbox: tuple[float, float, float, float] | None
    font_size: float


@dataclass(frozen=True, slots=True)
class ComposedPage:
    """Per-page build payload for typesetting/writing."""

    page_num: int
    width: float
    height: float
    overlay_blocks: tuple[ComposedTextBlock, ...]
    image_items: tuple[dict[str, Any], ...]
    footnote_items: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class BuildComposition:
    """Full composition object consumed by typesetter."""

    book_id: str
    source_pdf_path: Path
    pages: tuple[ComposedPage, ...]
    reflow_blocks: tuple[ComposedTextBlock, ...]
    translation_source: str
    translated_chunk_count: int
    mapped_block_count: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


class ComposerError(RuntimeError):
    """Raised when build composition cannot be produced."""


def compose_document(
    *,
    book_root: Path,
    prefer_edited: bool = True,
) -> BuildComposition:
    """Compose translated text blocks against document graph layout."""

    source_pdf_path = book_root / "input" / "original.pdf"
    if not source_pdf_path.exists():
        raise ComposerError(f"source PDF not found: {source_pdf_path}")

    graph_path = book_root / "analysis" / "document_graph.json"
    chunks_path = book_root / "analysis" / "chunks.jsonl"
    images_path = book_root / "analysis" / "images.jsonl"
    footnotes_path = book_root / "analysis" / "footnotes.jsonl"

    pages, blocks = _load_document_graph(graph_path)
    chunks_map = _load_chunks_map(chunks_path)
    if not chunks_map:
        raise ComposerError("analysis/chunks.jsonl is empty; nothing to build")

    translated_text_by_chunk, translation_source = _load_translation_map(
        translated_path=book_root / "translated" / "translated_chunks.jsonl",
        edited_path=book_root / "translated" / "edited_chunks.jsonl",
        prefer_edited=prefer_edited,
    )

    if not translated_text_by_chunk:
        raise ComposerError("no completed translated chunks found")

    images_rows = _load_jsonl(images_path)
    footnote_rows = _load_jsonl(footnotes_path)

    block_by_id = {block.block_id: block for block in blocks}
    block_translation: dict[str, str] = {}
    block_chunk_source: dict[str, str] = {}
    warnings: list[str] = []

    mapped_chunks = 0
    for chunk_id, translated_text in translated_text_by_chunk.items():
        chunk = chunks_map.get(chunk_id)
        if chunk is None:
            warnings.append(f"translated chunk {chunk_id}: chunk metadata missing in chunks.jsonl")
            continue

        available_block_ids = [block_id for block_id in chunk.block_ids if block_id in block_by_id]
        if not available_block_ids:
            warnings.append(f"translated chunk {chunk_id}: no target blocks from document graph")
            continue

        segments = _split_text_for_blocks(translated_text, len(available_block_ids))
        for block_id, segment in zip(available_block_ids, segments, strict=True):
            text = segment.strip()
            if not text:
                continue
            if block_id in block_translation:
                block_translation[block_id] = f"{block_translation[block_id]}\n\n{text}"
            else:
                block_translation[block_id] = text
            block_chunk_source.setdefault(block_id, chunk_id)

        mapped_chunks += 1

    if not block_translation:
        raise ComposerError("translated chunks were loaded but no block mappings were produced")

    page_by_num = {page.page_num: page for page in pages}
    ordered_page_nums = sorted(page_by_num)
    if not ordered_page_nums:
        ordered_page_nums = sorted({block.page_num for block in blocks})

    blocks_by_page: dict[int, list[Block]] = {}
    for block in blocks:
        blocks_by_page.setdefault(block.page_num, []).append(block)

    composed_pages: list[ComposedPage] = []
    reflow_blocks: list[ComposedTextBlock] = []

    for page_num in ordered_page_nums:
        page = page_by_num.get(page_num)
        page_width = float(page.width) if page and page.width else 595.0
        page_height = float(page.height) if page and page.height else 842.0

        page_blocks = blocks_by_page.get(page_num, [])
        if page and page.block_ids:
            page_blocks = [block_by_id[item] for item in page.block_ids if item in block_by_id]
        page_blocks = sorted(page_blocks, key=lambda block: block.reading_order)

        overlay_blocks: list[ComposedTextBlock] = []

        for block in page_blocks:
            translated = block_translation.get(block.block_id)
            if translated is None:
                continue
            if block.block_type not in TEXT_BLOCK_TYPES:
                warnings.append(
                    f"block {block.block_id}: translated text exists but block_type={block.block_type} is non-text; skipped"
                )
                continue

            composed = ComposedTextBlock(
                block_id=block.block_id,
                chunk_id=block_chunk_source.get(block.block_id, ""),
                page_num=block.page_num,
                block_type=block.block_type,
                text=translated,
                bbox=block.bbox,
                font_size=_resolve_font_size(block),
            )

            if block.bbox is None:
                reflow_blocks.append(composed)
            else:
                overlay_blocks.append(composed)

        page_images = tuple(item for item in images_rows if int(item.get("page_num", 0)) == page_num)
        page_footnotes = tuple(item for item in footnote_rows if int(item.get("page_num", 0)) == page_num)

        composed_pages.append(
            ComposedPage(
                page_num=page_num,
                width=page_width,
                height=page_height,
                overlay_blocks=tuple(overlay_blocks),
                image_items=page_images,
                footnote_items=page_footnotes,
            )
        )

    return BuildComposition(
        book_id=book_root.name,
        source_pdf_path=source_pdf_path,
        pages=tuple(composed_pages),
        reflow_blocks=tuple(reflow_blocks),
        translation_source=translation_source,
        translated_chunk_count=mapped_chunks,
        mapped_block_count=len(block_translation),
        warnings=tuple(warnings),
    )


def _load_document_graph(path: Path) -> tuple[list[PageInfo], list[Block]]:
    if not path.exists():
        raise ComposerError(f"document graph not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComposerError(f"invalid document_graph.json: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ComposerError("document_graph.json root must be an object")

    pages = [PageInfo.from_dict(item) for item in payload.get("pages", []) if isinstance(item, dict)]
    blocks = [Block.from_dict(item) for item in payload.get("blocks", []) if isinstance(item, dict)]

    if not blocks:
        raise ComposerError("document_graph.json contains no blocks")

    return pages, blocks


def _load_chunks_map(path: Path) -> dict[str, Chunk]:
    rows = _load_jsonl(path)
    mapping: dict[str, Chunk] = {}
    for row in rows:
        if "chunk_id" not in row:
            continue
        chunk = Chunk.from_dict(row)
        mapping[chunk.chunk_id] = chunk
    return mapping


def _load_translation_map(
    *, translated_path: Path, edited_path: Path, prefer_edited: bool
) -> tuple[dict[str, str], str]:
    translated_rows = _load_jsonl(translated_path)
    edited_rows = _load_jsonl(edited_path)

    base: dict[str, str] = {}
    for row in translated_rows:
        chunk_id = str(row.get("chunk_id", "")).strip()
        status = str(row.get("status", "")).strip()
        if not chunk_id or status != "completed":
            continue
        base[chunk_id] = str(row.get("target_text", ""))

    if prefer_edited:
        for row in edited_rows:
            chunk_id = str(row.get("chunk_id", "")).strip()
            status = str(row.get("status", "")).strip()
            if not chunk_id or status != "completed":
                continue
            base[chunk_id] = str(row.get("target_text", ""))

    source = (
        "edited_chunks.jsonl + fallback translated_chunks.jsonl"
        if prefer_edited and edited_rows
        else "translated_chunks.jsonl"
    )
    return base, source


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _resolve_font_size(block: Block) -> float:
    avg = block.style_metadata.get("avg_font_size")
    max_size = block.style_metadata.get("max_font_size")

    for value in (avg, max_size):
        if value is None:
            continue
        try:
            size = float(value)
        except (TypeError, ValueError):
            continue
        if size > 0:
            return max(8.0, min(size, 18.0))

    return 10.0


def _split_text_for_blocks(text: str, block_count: int) -> list[str]:
    clean = text.strip()
    if block_count <= 1:
        return [clean]
    if not clean:
        return [""] * block_count

    paragraphs = [item.strip() for item in re.split(r"\n{2,}|\r?\n", clean) if item.strip()]
    if len(paragraphs) >= block_count:
        head = paragraphs[: block_count - 1]
        tail = "\n\n".join(paragraphs[block_count - 1 :])
        return [*head, tail]

    return _split_evenly_by_sentences(clean, block_count)


def _split_evenly_by_sentences(text: str, count: int) -> list[str]:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]
    if len(sentences) < count:
        return _split_evenly_by_length(text, count)

    groups: list[list[str]] = [[] for _ in range(count)]
    index = 0
    for sentence in sentences:
        groups[index].append(sentence)
        if index < count - 1 and len(" ".join(groups[index])) >= len(text) / max(count, 1):
            index += 1

    result = [" ".join(group).strip() for group in groups]
    if any(result):
        return result
    return _split_evenly_by_length(text, count)


def _split_evenly_by_length(text: str, count: int) -> list[str]:
    if count <= 1:
        return [text]

    average = max(1, len(text) // count)
    parts: list[str] = []
    cursor = 0
    for index in range(count):
        if index == count - 1:
            parts.append(text[cursor:].strip())
            break
        next_cursor = min(len(text), cursor + average)
        if next_cursor < len(text):
            space_idx = text.rfind(" ", cursor, next_cursor + 1)
            if space_idx > cursor:
                next_cursor = space_idx
        parts.append(text[cursor:next_cursor].strip())
        cursor = next_cursor

    while len(parts) < count:
        parts.append("")

    return parts[:count]
