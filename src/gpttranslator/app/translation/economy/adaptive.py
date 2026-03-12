"""Adaptive chunk sizing and transformation heuristics."""

from __future__ import annotations

from dataclasses import replace

from ...core.models import Chunk
from .complexity import assess_chunk_complexity
from .profiles import EconomyProfile


def adapt_chunks(chunks: list[Chunk], *, profile: EconomyProfile, enabled: bool) -> list[Chunk]:
    """Apply deterministic split/merge strategy for adaptive chunk sizing."""

    if not enabled or not chunks:
        return chunks

    split_applied = _split_complex_chunks(chunks, profile=profile)
    merged = _merge_simple_chunks(split_applied, profile=profile)
    return merged


def _split_complex_chunks(chunks: list[Chunk], *, profile: EconomyProfile) -> list[Chunk]:
    adapted: list[Chunk] = []

    for chunk in chunks:
        assessment = assess_chunk_complexity(chunk)
        if (
            chunk.chunk_type == "paragraph_group"
            and assessment.score >= max(0.74, profile.tier_c_threshold)
            and len(chunk.block_ids) > 1
        ):
            groups = _partition(chunk.block_ids, max_group_size=max(1, profile.chunk_max_blocks // 2))
            lines = [line for line in chunk.source_text.splitlines() if line.strip()]

            for index, group in enumerate(groups, start=1):
                text = lines[index - 1] if index - 1 < len(lines) else chunk.source_text
                metadata = dict(chunk.metadata)
                metadata.update({
                    "adaptive": "split",
                    "adaptive_parent": chunk.chunk_id,
                })
                adapted.append(
                    replace(
                        chunk,
                        chunk_id=f"{chunk.chunk_id}-s{index}",
                        block_ids=list(group),
                        source_text=text,
                        token_estimate=max(1, int(len(text) / 4)),
                        metadata=metadata,
                    )
                )
            continue

        adapted.append(chunk)

    return adapted


def _merge_simple_chunks(chunks: list[Chunk], *, profile: EconomyProfile) -> list[Chunk]:
    merged: list[Chunk] = []
    idx = 0

    while idx < len(chunks):
        current = chunks[idx]
        if idx + 1 >= len(chunks):
            merged.append(current)
            break

        nxt = chunks[idx + 1]
        if not _can_merge(current, nxt, profile=profile):
            merged.append(current)
            idx += 1
            continue

        combined_text = "\n".join([current.source_text.strip(), nxt.source_text.strip()]).strip()
        combined_ids = [*current.block_ids, *nxt.block_ids]
        combined_footnotes = [*current.footnote_refs, *nxt.footnote_refs]
        metadata = dict(current.metadata)
        metadata.update({
            "adaptive": "merge",
            "adaptive_children": [current.chunk_id, nxt.chunk_id],
        })

        merged_chunk = replace(
            current,
            chunk_id=f"{current.chunk_id}+{nxt.chunk_id}",
            block_ids=combined_ids,
            source_text=combined_text,
            local_context_after=nxt.local_context_after,
            footnote_refs=combined_footnotes,
            token_estimate=max(1, int(len(combined_text) / 4)),
            metadata=metadata,
        )
        merged.append(merged_chunk)
        idx += 2

    return merged


def _can_merge(left: Chunk, right: Chunk, *, profile: EconomyProfile) -> bool:
    if left.chunk_type != "paragraph_group" or right.chunk_type != "paragraph_group":
        return False
    if left.chapter_id != right.chapter_id:
        return False
    if left.footnote_refs or right.footnote_refs:
        return False

    left_score = assess_chunk_complexity(left).score
    right_score = assess_chunk_complexity(right).score
    if left_score >= 0.25 or right_score >= 0.25:
        return False

    combined_chars = len(left.source_text) + len(right.source_text)
    combined_blocks = len(left.block_ids) + len(right.block_ids)
    if combined_chars > int(profile.chunk_max_chars * 1.5):
        return False
    if combined_blocks > int(profile.chunk_max_blocks * 1.5):
        return False
    return True


def _partition(items: list[str], *, max_group_size: int) -> list[list[str]]:
    if max_group_size <= 0:
        return [items]
    groups: list[list[str]] = []
    for start in range(0, len(items), max_group_size):
        groups.append(items[start : start + max_group_size])
    return groups
