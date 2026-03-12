"""Translation memory matching primitives for cost-aware reuse."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from ...memory.translation_memory_manager import TranslationMemoryEntry


@dataclass(frozen=True, slots=True)
class TMMatchedEntry:
    """Scored translation-memory candidate."""

    entry: TranslationMemoryEntry
    similarity: float
    exact: bool


def normalize_text(text: str) -> str:
    """Normalize text for stable local matching."""

    compact = re.sub(r"\s+", " ", text.strip().lower())
    return compact


def similarity_ratio(source: str, candidate: str) -> float:
    """Compute deterministic normalized similarity ratio."""

    left = normalize_text(source)
    right = normalize_text(candidate)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def find_tm_matches(
    source_text: str,
    tm_entries: list[TranslationMemoryEntry],
    *,
    chapter_id: str | None = None,
    exact_threshold: float = 0.995,
    near_threshold: float = 0.92,
    limit: int = 5,
) -> list[TMMatchedEntry]:
    """Find exact/near matches sorted by relevance and chapter locality."""

    scored: list[tuple[float, TMMatchedEntry]] = []

    for entry in tm_entries:
        ratio = similarity_ratio(source_text, entry.source_text)
        if ratio < near_threshold:
            continue

        chapter_bonus = 0.02 if chapter_id and entry.chapter_id == chapter_id else 0.0
        rank_score = min(ratio + chapter_bonus, 1.0)
        match = TMMatchedEntry(
            entry=entry,
            similarity=ratio,
            exact=ratio >= exact_threshold,
        )
        scored.append((rank_score, match))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[: max(1, limit)]]


def find_exact_tm_match(
    source_text: str,
    tm_entries: list[TranslationMemoryEntry],
    *,
    chapter_id: str | None = None,
    exact_threshold: float = 0.995,
) -> TMMatchedEntry | None:
    """Return best exact TM match if available."""

    matches = find_tm_matches(
        source_text,
        tm_entries,
        chapter_id=chapter_id,
        exact_threshold=exact_threshold,
        near_threshold=exact_threshold,
        limit=1,
    )
    if not matches:
        return None
    return matches[0] if matches[0].exact else None
