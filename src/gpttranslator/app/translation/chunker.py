"""Local chunking for future translation jobs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.models import Block, Chunk, FootnoteLink
from ..pdf.document_graph import DocumentGraph

_ALLOWED_TYPES = {
    "paragraph_group",
    "caption",
    "footnote",
    "heading",
    "auxiliary",
}


class ChunkingError(RuntimeError):
    """Raised when chunking output is inconsistent or invalid."""


@dataclass(frozen=True)
class ChunkerSettings:
    """Chunking size and context settings."""

    max_chars: int = 1200
    max_blocks: int = 8
    context_blocks: int = 2
    context_chars: int = 280
    max_glossary_hints: int = 12


@dataclass(slots=True)
class _ChunkDraft:
    chunk_type: str
    block_ids: list[str]
    chapter_id: str
    start_index: int
    end_index: int
    flags: list[str]


def build_translation_chunks(
    graph: DocumentGraph,
    settings: ChunkerSettings | None = None,
) -> list[Chunk]:
    """Build translation chunks from document graph."""

    cfg = settings or ChunkerSettings()
    _validate_settings(cfg)

    ordered_blocks = sorted(graph.blocks, key=lambda item: (item.page_num, item.reading_order, item.block_id))
    if not ordered_blocks:
        return []

    refs_by_block = _footnote_refs_by_block(graph.footnote_links)

    drafts = _build_chunk_drafts(ordered_blocks=ordered_blocks, settings=cfg)
    chunks: list[Chunk] = []

    for idx, draft in enumerate(drafts, start=1):
        member_blocks = [block for block in ordered_blocks if block.block_id in set(draft.block_ids)]
        source_text = "\n".join(block.text.strip() for block in member_blocks if block.text.strip()).strip()

        if not source_text:
            source_text = "\n".join(block.text for block in member_blocks).strip()

        page_values = [block.page_num for block in member_blocks]
        page_range = (
            (min(page_values), max(page_values))
            if page_values
            else (1, 1)
        )

        footnote_refs = _collect_chunk_footnote_refs(draft.block_ids, refs_by_block)

        before_text, after_text = _build_local_context(
            ordered_blocks=ordered_blocks,
            start_index=draft.start_index,
            end_index=draft.end_index,
            context_blocks=cfg.context_blocks,
            context_chars=cfg.context_chars,
        )

        chunk = Chunk(
            chunk_id=f"chk-{idx:05d}",
            chapter_id=draft.chapter_id,
            page_range=page_range,
            block_ids=list(draft.block_ids),
            chunk_type=draft.chunk_type,
            source_text=source_text,
            local_context_before=before_text,
            local_context_after=after_text,
            footnote_refs=footnote_refs,
            glossary_hints=_extract_glossary_hints(source_text, max_hints=cfg.max_glossary_hints),
            token_estimate=_estimate_tokens(source_text),
            metadata={
                "flags": draft.flags,
            },
        )
        chunks.append(chunk)

    validate_chunks(chunks=chunks, graph=graph)
    return chunks


def save_chunks_jsonl(path: Path, chunks: list[Chunk]) -> str:
    """Persist chunks to JSONL file."""

    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    return str(target)


def validate_chunks(chunks: list[Chunk], graph: DocumentGraph) -> None:
    """Validate chunk records and cross references to graph blocks."""

    errors: list[str] = []
    ids: set[str] = set()
    block_by_id = {block.block_id: block for block in graph.blocks}

    for chunk in chunks:
        if not chunk.chunk_id:
            errors.append("chunk_id is empty")
            continue

        if chunk.chunk_id in ids:
            errors.append(f"duplicate chunk_id: {chunk.chunk_id}")
        ids.add(chunk.chunk_id)

        if chunk.chunk_type not in _ALLOWED_TYPES:
            errors.append(f"chunk {chunk.chunk_id}: unsupported chunk_type {chunk.chunk_type}")

        if not chunk.block_ids:
            errors.append(f"chunk {chunk.chunk_id}: no block_ids")
            continue

        missing = [block_id for block_id in chunk.block_ids if block_id not in block_by_id]
        if missing:
            errors.append(f"chunk {chunk.chunk_id}: missing block references {missing}")
            continue

        page_range = chunk.page_range
        if not page_range or len(page_range) != 2:
            errors.append(f"chunk {chunk.chunk_id}: invalid page_range")
        else:
            if page_range[0] < 1 or page_range[1] < page_range[0]:
                errors.append(f"chunk {chunk.chunk_id}: invalid page_range values {page_range}")

        member_types = {block_by_id[block_id].block_type for block_id in chunk.block_ids}
        if chunk.chunk_type == "paragraph_group" and not member_types.issubset({"paragraph"}):
            errors.append(f"chunk {chunk.chunk_id}: paragraph_group mixed with {sorted(member_types)}")
        if chunk.chunk_type == "caption" and not member_types.issubset({"caption"}):
            errors.append(f"chunk {chunk.chunk_id}: caption mixed with {sorted(member_types)}")
        if chunk.chunk_type == "footnote" and not member_types.issubset({"footnote_body", "footnote_marker"}):
            errors.append(f"chunk {chunk.chunk_id}: footnote mixed with {sorted(member_types)}")
        if chunk.chunk_type == "heading" and not member_types.issubset({"heading"}):
            errors.append(f"chunk {chunk.chunk_id}: heading mixed with {sorted(member_types)}")
        if chunk.chunk_type == "auxiliary" and not member_types.issubset({"header", "footer", "image_anchor"}):
            errors.append(f"chunk {chunk.chunk_id}: auxiliary mixed with {sorted(member_types)}")

        if not chunk.source_text.strip():
            errors.append(f"chunk {chunk.chunk_id}: source_text is empty")

    if errors:
        details = "\n".join(f"- {item}" for item in errors[:50])
        raise ChunkingError(f"Chunk validation failed:\n{details}")


def _build_chunk_drafts(ordered_blocks: list[Block], settings: ChunkerSettings) -> list[_ChunkDraft]:
    drafts: list[_ChunkDraft] = []
    i = 0

    while i < len(ordered_blocks):
        block = ordered_blocks[i]
        chapter_id = block.section_id or "section-unknown"

        if block.block_type == "paragraph":
            chunk_block_ids = [block.block_id]
            char_count = len(block.text)
            j = i + 1

            while j < len(ordered_blocks):
                nxt = ordered_blocks[j]
                if nxt.block_type != "paragraph" or (nxt.section_id or "section-unknown") != chapter_id:
                    break

                projected_chars = char_count + 1 + len(nxt.text)
                if len(chunk_block_ids) >= settings.max_blocks or projected_chars > settings.max_chars:
                    break

                chunk_block_ids.append(nxt.block_id)
                char_count = projected_chars
                j += 1

            drafts.append(
                _ChunkDraft(
                    chunk_type="paragraph_group",
                    block_ids=chunk_block_ids,
                    chapter_id=chapter_id,
                    start_index=i,
                    end_index=j - 1,
                    flags=[],
                )
            )
            i = j
            continue

        mapped_type = _map_block_type_to_chunk_type(block.block_type)
        draft_flags: list[str] = []
        if mapped_type == "auxiliary":
            draft_flags.append("non_primary_translation_unit")

        drafts.append(
            _ChunkDraft(
                chunk_type=mapped_type,
                block_ids=[block.block_id],
                chapter_id=chapter_id,
                start_index=i,
                end_index=i,
                flags=draft_flags,
            )
        )
        i += 1

    return drafts


def _map_block_type_to_chunk_type(block_type: str) -> str:
    if block_type == "heading":
        return "heading"
    if block_type == "caption":
        return "caption"
    if block_type in {"footnote_body", "footnote_marker"}:
        return "footnote"
    if block_type in {"paragraph"}:
        return "paragraph_group"
    return "auxiliary"


def _collect_chunk_footnote_refs(
    block_ids: list[str],
    refs_by_block: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for block_id in block_ids:
        for ref in refs_by_block.get(block_id, []):
            ref_id = str(ref.get("link_id", ""))
            if ref_id and ref_id in seen:
                continue
            refs.append(ref)
            if ref_id:
                seen.add(ref_id)

    return refs


def _build_local_context(
    ordered_blocks: list[Block],
    start_index: int,
    end_index: int,
    context_blocks: int,
    context_chars: int,
) -> tuple[str, str]:
    before_start = max(0, start_index - context_blocks)
    before_blocks = ordered_blocks[before_start:start_index]

    after_end = min(len(ordered_blocks), end_index + 1 + context_blocks)
    after_blocks = ordered_blocks[end_index + 1 : after_end]

    before_text = "\n".join(block.text.strip() for block in before_blocks if block.text.strip())
    after_text = "\n".join(block.text.strip() for block in after_blocks if block.text.strip())

    return _tail(before_text, context_chars), _head(after_text, context_chars)


def _head(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip()


def _tail(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[-max_len:].lstrip()


def _extract_glossary_hints(text: str, max_hints: int) -> list[str]:
    acronyms = re.findall(r"\b[A-Z]{2,}\b", text)
    title_sequences = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", text)

    candidates = [*acronyms, *title_sequences]
    unique: list[str] = []
    seen: set[str] = set()

    for item in candidates:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= max_hints:
            break

    return unique


def _footnote_refs_by_block(links: list[FootnoteLink]) -> dict[str, list[dict[str, Any]]]:
    refs_by_block: dict[str, list[dict[str, Any]]] = {}

    for link in links:
        payload = {
            "link_id": link.link_id,
            "marker": link.marker,
            "marker_block_id": link.marker_block_id,
            "body_block_id": link.body_block_id,
            "confidence": link.confidence,
            "flags": list(link.flags),
        }

        for block_id in [link.marker_block_id, link.body_block_id]:
            if not block_id:
                continue
            refs_by_block.setdefault(block_id, []).append(payload)

    return refs_by_block


def _estimate_tokens(text: str) -> int:
    words = len(re.findall(r"\S+", text))
    return max(1, int(words * 1.3))


def _validate_settings(settings: ChunkerSettings) -> None:
    if settings.max_chars < 200:
        raise ChunkingError("max_chars must be >= 200")
    if settings.max_blocks < 1:
        raise ChunkingError("max_blocks must be >= 1")
    if settings.context_blocks < 0:
        raise ChunkingError("context_blocks must be >= 0")
    if settings.context_chars < 0:
        raise ChunkingError("context_chars must be >= 0")
    if settings.max_glossary_hints < 0:
        raise ChunkingError("max_glossary_hints must be >= 0")
