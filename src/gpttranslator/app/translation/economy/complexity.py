"""Chunk complexity scoring and tier routing heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ...core.models import Chunk

ChunkTier = Literal["A", "B", "C"]
_FOOTNOTE_PATTERN = re.compile(r"\[(?:\d+|\w+)\]")


@dataclass(frozen=True, slots=True)
class ComplexityFeatures:
    """Low-level features driving chunk complexity score."""

    char_count: int
    footnote_markers: int
    rare_term_count: int
    digit_ratio: float
    formula_ratio: float
    list_density: float
    table_like: bool
    unusual_layout: bool


@dataclass(frozen=True, slots=True)
class ComplexityAssessment:
    """Normalized score and reasons for tier routing."""

    score: float
    features: ComplexityFeatures
    risk_flags: tuple[str, ...]


def assess_chunk_complexity(chunk: Chunk) -> ComplexityAssessment:
    """Compute complexity score in [0, 1] using deterministic heuristics."""

    text = chunk.source_text or ""
    char_count = len(text)
    footnote_markers = _count_footnote_markers(chunk)
    rare_term_count = _count_rare_terms(chunk)

    if char_count == 0:
        digit_ratio = 0.0
        formula_ratio = 0.0
    else:
        digit_ratio = sum(1 for ch in text if ch.isdigit()) / char_count
        formula_chars = set("=+-/*^%<>[]{}")
        formula_ratio = sum(1 for ch in text if ch in formula_chars) / char_count

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        list_lines = sum(1 for line in lines if _is_list_line(line))
        list_density = list_lines / len(lines)
    else:
        list_density = 0.0

    table_like = "|" in text and "\n" in text

    flags = chunk.metadata.get("flags", []) if isinstance(chunk.metadata, dict) else []
    unusual_layout = bool(flags) or chunk.chunk_type in {"caption", "footnote", "heading", "auxiliary"}

    score = (
        min(char_count / 1800.0, 1.0) * 0.25
        + min(footnote_markers / 4.0, 1.0) * 0.2
        + min(rare_term_count / 8.0, 1.0) * 0.15
        + min((digit_ratio + formula_ratio) * 3.0, 1.0) * 0.15
        + min((list_density * 2.0) + (0.5 if table_like else 0.0), 1.0) * 0.15
        + (0.1 if unusual_layout else 0.0)
    )
    score = max(0.0, min(score, 1.0))

    risk_flags: list[str] = []
    if footnote_markers > 0:
        risk_flags.append("footnote_markers")
    if rare_term_count >= 3:
        risk_flags.append("terminology_dense")
    if (digit_ratio + formula_ratio) >= 0.12:
        risk_flags.append("numeric_or_formula_dense")
    if list_density >= 0.25 or table_like:
        risk_flags.append("list_or_table_structure")
    if unusual_layout:
        risk_flags.append("layout_sensitive")

    return ComplexityAssessment(
        score=score,
        features=ComplexityFeatures(
            char_count=char_count,
            footnote_markers=footnote_markers,
            rare_term_count=rare_term_count,
            digit_ratio=digit_ratio,
            formula_ratio=formula_ratio,
            list_density=list_density,
            table_like=table_like,
            unusual_layout=unusual_layout,
        ),
        risk_flags=tuple(risk_flags),
    )


def route_chunk_tier(
    assessment: ComplexityAssessment,
    *,
    tier_b_threshold: float,
    tier_c_threshold: float,
) -> ChunkTier:
    """Route chunk into tier A/B/C from complexity score."""

    if assessment.score >= tier_c_threshold:
        return "C"
    if assessment.score >= tier_b_threshold:
        return "B"
    return "A"


def _count_footnote_markers(chunk: Chunk) -> int:
    refs = len(chunk.footnote_refs)
    inline = len(set(_FOOTNOTE_PATTERN.findall(chunk.source_text or "")))
    return max(refs, inline)


def _count_rare_terms(chunk: Chunk) -> int:
    hints = chunk.glossary_hints or []
    if hints:
        return len(set(str(item).strip().lower() for item in hints if str(item).strip()))

    words = re.findall(r"\b[A-Za-z][A-Za-z\-]{5,}\b", chunk.source_text or "")
    uncommon = [word for word in words if word.lower() not in _COMMON_ENGLISH]
    return min(len(set(uncommon)), 10)


def _is_list_line(line: str) -> bool:
    if line.startswith(("- ", "* ", "• ")):
        return True
    return bool(re.match(r"^\d+[\.)]\s+", line))


_COMMON_ENGLISH: frozenset[str] = frozenset(
    {
        "about",
        "after",
        "before",
        "because",
        "between",
        "chapter",
        "example",
        "general",
        "information",
        "language",
        "method",
        "number",
        "people",
        "process",
        "result",
        "section",
        "system",
        "theory",
        "through",
        "without",
    }
)
