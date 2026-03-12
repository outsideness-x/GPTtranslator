"""Local pre-filter and TM-first reuse decisions before Codex calls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ...core.models import Chunk
from ...memory.translation_memory_manager import TranslationMemoryEntry
from .tm import TMMatchedEntry, find_tm_matches, normalize_text

PreFilterAction = Literal["skip", "reuse", "codex"]


@dataclass(frozen=True, slots=True)
class PreFilterDecision:
    """Decision about whether chunk should call Codex."""

    action: PreFilterAction
    reason: str
    target_text: str = ""
    tm_match: TMMatchedEntry | None = None


@dataclass(frozen=True, slots=True)
class PreFilterSettings:
    """Configurable thresholds for local pre-filtering."""

    tm_first: bool = True
    exact_threshold: float = 0.995
    near_threshold: float = 0.93
    allow_near_reuse: bool = True


def decide_prefilter_action(
    chunk: Chunk,
    *,
    tm_entries: list[TranslationMemoryEntry],
    repeated_translations: dict[str, str],
    settings: PreFilterSettings,
) -> PreFilterDecision:
    """Determine whether chunk needs Codex or can be handled locally."""

    source_text = chunk.source_text.strip()
    source_key = normalize_text(source_text)

    if not source_text:
        return PreFilterDecision(action="skip", reason="empty_source")

    if _is_non_translatable_fragment(chunk, source_text):
        return PreFilterDecision(action="skip", reason="non_translatable_fragment", target_text=source_text)

    if source_key in repeated_translations:
        return PreFilterDecision(
            action="reuse",
            reason="repeated_approved_translation",
            target_text=repeated_translations[source_key],
        )

    if settings.tm_first:
        tm_matches = find_tm_matches(
            source_text,
            tm_entries,
            chapter_id=chunk.chapter_id,
            exact_threshold=settings.exact_threshold,
            near_threshold=settings.near_threshold,
            limit=3,
        )

        if tm_matches:
            best = tm_matches[0]
            if best.exact:
                return PreFilterDecision(
                    action="reuse",
                    reason="translation_memory_exact",
                    target_text=best.entry.target_text,
                    tm_match=best,
                )

            if settings.allow_near_reuse and best.similarity >= settings.near_threshold + 0.03:
                return PreFilterDecision(
                    action="reuse",
                    reason="translation_memory_near",
                    target_text=best.entry.target_text,
                    tm_match=best,
                )

    return PreFilterDecision(action="codex", reason="requires_model_translation")


def _is_non_translatable_fragment(chunk: Chunk, source_text: str) -> bool:
    if re.fullmatch(r"\d+(?:[\./-]\d+)*", source_text):
        return True

    if chunk.chunk_type == "auxiliary" and len(source_text) <= 80:
        upper = sum(1 for ch in source_text if ch.isupper())
        alpha = sum(1 for ch in source_text if ch.isalpha())
        if alpha == 0:
            return True
        if upper / alpha >= 0.65:
            return True

    if re.fullmatch(r"[\W_]+", source_text):
        return True

    return False
