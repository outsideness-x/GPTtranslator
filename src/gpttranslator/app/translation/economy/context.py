"""Context minimization and retrieval for per-chunk Codex prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ...core.models import Chunk
from ...memory.glossary_manager import GlossaryEntry
from ...memory.translation_memory_manager import TranslationMemoryEntry
from .tm import TMMatchedEntry, find_tm_matches, normalize_text, similarity_ratio


@dataclass(frozen=True, slots=True)
class ContextBuildSettings:
    """Limits used to keep prompt context compact."""

    max_context_entries: int = 12
    max_glossary_exact: int = 10
    max_glossary_fuzzy: int = 6
    max_tm_matches: int = 5
    max_style_rules: int = 8
    chapter_notes_char_limit: int = 800


@dataclass(frozen=True, slots=True)
class ContextPackage:
    """Minimal context package injected into prompt input."""

    exact_glossary: tuple[GlossaryEntry, ...]
    fuzzy_glossary: tuple[GlossaryEntry, ...]
    named_entities: tuple[str, ...]
    chapter_term_decisions: tuple[dict[str, str], ...]
    style_rules: tuple[str, ...]
    chapter_notes_excerpt: str
    tm_matches: tuple[TMMatchedEntry, ...]
    context_weight: int

    def to_compact_payload(self) -> dict[str, object]:
        """Serialize context package to compact deterministic structure."""

        return {
            "exact_glossary": [
                {"s": item.source_term, "t": item.target_term, "n": item.notes} for item in self.exact_glossary
            ],
            "fuzzy_glossary": [
                {"s": item.source_term, "t": item.target_term, "n": item.notes} for item in self.fuzzy_glossary
            ],
            "entities": list(self.named_entities),
            "chapter_decisions": list(self.chapter_term_decisions),
            "style_rules": list(self.style_rules),
            "chapter_notes": self.chapter_notes_excerpt,
            "tm_matches": [
                {
                    "src": item.entry.source_text,
                    "tgt": item.entry.target_text,
                    "sim": round(item.similarity, 4),
                    "exact": item.exact,
                    "chunk_id": item.entry.chunk_id,
                }
                for item in self.tm_matches
            ],
        }


def build_context_package(
    chunk: Chunk,
    *,
    glossary_entries: list[GlossaryEntry],
    tm_entries: list[TranslationMemoryEntry],
    style_guide_text: str,
    chapter_notes_text: str,
    settings: ContextBuildSettings,
    tm_exact_threshold: float,
    tm_near_threshold: float,
) -> ContextPackage:
    """Build minimal context package for one chunk without model calls."""

    exact_hits, fuzzy_hits = slice_glossary_entries(
        chunk.source_text,
        glossary_entries,
        max_exact=settings.max_glossary_exact,
        max_fuzzy=settings.max_glossary_fuzzy,
    )

    tm_matches = tuple(
        find_tm_matches(
            chunk.source_text,
            tm_entries,
            chapter_id=chunk.chapter_id,
            exact_threshold=tm_exact_threshold,
            near_threshold=tm_near_threshold,
            limit=settings.max_tm_matches,
        )
    )

    named_entities = tuple(extract_named_entities(chunk, limit=settings.max_context_entries))
    chapter_term_decisions = tuple(
        _chapter_term_decisions(
            chunk=chunk,
            tm_entries=tm_entries,
            limit=max(2, settings.max_context_entries // 2),
        )
    )
    style_rules = tuple(
        slice_style_rules(
            style_guide_text,
            chunk.source_text,
            max_rules=settings.max_style_rules,
        )
    )
    chapter_notes_excerpt = slice_chapter_notes(
        chapter_notes_text,
        chapter_id=chunk.chapter_id,
        max_chars=settings.chapter_notes_char_limit,
    )

    weight = _estimate_context_weight(
        exact_hits=exact_hits,
        fuzzy_hits=fuzzy_hits,
        named_entities=named_entities,
        chapter_term_decisions=chapter_term_decisions,
        style_rules=style_rules,
        chapter_notes_excerpt=chapter_notes_excerpt,
        tm_matches=tm_matches,
    )

    return ContextPackage(
        exact_glossary=tuple(exact_hits[: settings.max_glossary_exact]),
        fuzzy_glossary=tuple(fuzzy_hits[: settings.max_glossary_fuzzy]),
        named_entities=named_entities[: settings.max_context_entries],
        chapter_term_decisions=chapter_term_decisions[: settings.max_context_entries],
        style_rules=style_rules[: settings.max_style_rules],
        chapter_notes_excerpt=chapter_notes_excerpt,
        tm_matches=tm_matches[: settings.max_tm_matches],
        context_weight=weight,
    )


def slice_glossary_entries(
    source_text: str,
    glossary_entries: list[GlossaryEntry],
    *,
    max_exact: int,
    max_fuzzy: int,
) -> tuple[list[GlossaryEntry], list[GlossaryEntry]]:
    """Return exact and fuzzy glossary subset relevant to source text."""

    text_norm = normalize_text(source_text)
    tokens = _tokenize(source_text)

    exact: list[GlossaryEntry] = []
    fuzzy: list[tuple[float, GlossaryEntry]] = []

    for entry in glossary_entries:
        source_term = entry.source_term.strip()
        if not source_term:
            continue

        term_norm = normalize_text(source_term)
        if not term_norm:
            continue

        if _contains_term(text_norm, term_norm):
            exact.append(entry)
            continue

        fuzzy_score = _fuzzy_term_score(term_norm, tokens)
        if fuzzy_score >= 0.84:
            fuzzy.append((fuzzy_score, entry))

    fuzzy.sort(key=lambda item: item[0], reverse=True)

    dedup_exact = _deduplicate_glossary(exact)
    dedup_fuzzy = _deduplicate_glossary([item[1] for item in fuzzy])

    return dedup_exact[:max_exact], dedup_fuzzy[:max_fuzzy]


def extract_named_entities(chunk: Chunk, *, limit: int) -> list[str]:
    """Extract named entities from local chunk window using regex heuristics."""

    text = "\n".join(
        [
            chunk.local_context_before,
            chunk.source_text,
            chunk.local_context_after,
        ]
    )
    acronyms = re.findall(r"\b[A-Z]{2,}\b", text)
    names = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b", text)

    seen: set[str] = set()
    result: list[str] = []
    for candidate in [*acronyms, *names]:
        normalized = candidate.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(candidate)
        if len(result) >= limit:
            break
    return result


def slice_style_rules(style_guide_text: str, source_text: str, *, max_rules: int) -> list[str]:
    """Slice style guide to only relevant bullet rules for current chunk."""

    rules = _extract_bullets(style_guide_text)
    if not rules:
        return []

    keywords = set(_tokenize(source_text))
    scored: list[tuple[float, str]] = []

    for rule in rules:
        rule_tokens = set(_tokenize(rule))
        overlap = len(keywords & rule_tokens)
        coverage = overlap / max(1, len(rule_tokens))
        scored.append((coverage, rule))

    scored.sort(key=lambda item: item[0], reverse=True)

    selected: list[str] = []
    for score, rule in scored:
        if score <= 0 and selected:
            continue
        selected.append(rule)
        if len(selected) >= max_rules:
            break

    if not selected:
        selected = rules[:max_rules]

    return selected[:max_rules]


def slice_chapter_notes(chapter_notes_text: str, *, chapter_id: str | None, max_chars: int) -> str:
    """Extract compact chapter notes snippet (global + nearest chapter section)."""

    if not chapter_notes_text.strip():
        return ""

    sections = _split_markdown_sections(chapter_notes_text)
    selected: list[str] = []

    global_section = sections.get("global notes")
    if global_section:
        selected.append(global_section)

    if chapter_id:
        chapter_key = chapter_id.lower()
        for heading, body in sections.items():
            if heading == "global notes":
                continue
            if chapter_key in heading:
                selected.append(body)
                break

    if not selected:
        selected.append(chapter_notes_text)

    combined = "\n\n".join(item.strip() for item in selected if item.strip())
    combined = re.sub(r"\n{3,}", "\n\n", combined)
    if len(combined) <= max_chars:
        return combined
    return combined[:max_chars].rstrip()


def _chapter_term_decisions(
    *,
    chunk: Chunk,
    tm_entries: list[TranslationMemoryEntry],
    limit: int,
) -> list[dict[str, str]]:
    text_norm = normalize_text(chunk.source_text)
    decisions: list[dict[str, str]] = []

    for entry in tm_entries:
        if chunk.chapter_id and entry.chapter_id != chunk.chapter_id:
            continue
        if not entry.notes and not entry.quality:
            continue

        quality = (entry.quality or "").lower()
        notes = (entry.notes or "").lower()
        if "approved" not in quality and "approved" not in notes and "locked" not in quality:
            continue

        source_norm = normalize_text(entry.source_text)
        if source_norm and source_norm not in text_norm:
            ratio = similarity_ratio(chunk.source_text, entry.source_text)
            if ratio < 0.86:
                continue

        decisions.append(
            {
                "source": entry.source_text,
                "target": entry.target_text,
                "reason": entry.quality or entry.notes or "approved_in_chapter",
            }
        )

        if len(decisions) >= limit:
            break

    return decisions


def _extract_bullets(markdown_text: str) -> list[str]:
    bullets: list[str] = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            bullets.append(line[2:].strip())
    return bullets


def _split_markdown_sections(markdown_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_heading: str | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current_heading, body_lines
        if current_heading is not None:
            sections[current_heading] = "\n".join(body_lines).strip()

    for line in markdown_text.splitlines():
        if line.startswith("## "):
            flush()
            current_heading = line[3:].strip().lower()
            body_lines = []
            continue
        if current_heading is not None:
            body_lines.append(line)

    flush()
    return sections


def _estimate_context_weight(
    *,
    exact_hits: Iterable[GlossaryEntry],
    fuzzy_hits: Iterable[GlossaryEntry],
    named_entities: Iterable[str],
    chapter_term_decisions: Iterable[dict[str, str]],
    style_rules: Iterable[str],
    chapter_notes_excerpt: str,
    tm_matches: Iterable[TMMatchedEntry],
) -> int:
    total = 0
    for entry in exact_hits:
        total += len(entry.source_term) + len(entry.target_term) + len(entry.notes)
    for entry in fuzzy_hits:
        total += len(entry.source_term) + len(entry.target_term)
    for entity in named_entities:
        total += len(entity)
    for decision in chapter_term_decisions:
        total += len(decision.get("source", "")) + len(decision.get("target", ""))
    for rule in style_rules:
        total += len(rule)
    total += len(chapter_notes_excerpt)
    for match in tm_matches:
        total += len(match.entry.source_text) + len(match.entry.target_text)
    return total


def _deduplicate_glossary(entries: list[GlossaryEntry]) -> list[GlossaryEntry]:
    deduped: list[GlossaryEntry] = []
    seen: set[str] = set()
    for entry in entries:
        key = normalize_text(entry.source_term)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _contains_term(text_norm: str, term_norm: str) -> bool:
    if term_norm in text_norm:
        return True
    return bool(re.search(rf"\b{re.escape(term_norm)}\b", text_norm))


def _fuzzy_term_score(term_norm: str, tokens: list[str]) -> float:
    if not tokens:
        return 0.0

    best = 0.0
    for token in tokens:
        if not token:
            continue
        if token.startswith(term_norm) or term_norm.startswith(token):
            best = max(best, 0.9)
            continue
        best = max(best, similarity_ratio(term_norm, token))
    return best


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-zА-Яа-яЁё0-9\-]+", text.lower())
