"""Translation memory JSONL management and local lookups."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TranslationMemoryEntry:
    source_text: str
    target_text: str
    chapter_id: str | None = None
    chunk_id: str | None = None
    quality: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_text": self.source_text,
            "target_text": self.target_text,
            "chapter_id": self.chapter_id,
            "chunk_id": self.chunk_id,
            "quality": self.quality,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranslationMemoryEntry":
        return cls(
            source_text=str(data.get("source_text", "")),
            target_text=str(data.get("target_text", "")),
            chapter_id=(str(data["chapter_id"]) if data.get("chapter_id") is not None else None),
            chunk_id=(str(data["chunk_id"]) if data.get("chunk_id") is not None else None),
            quality=(str(data["quality"]) if data.get("quality") is not None else None),
            notes=(str(data["notes"]) if data.get("notes") is not None else None),
        )


@dataclass(slots=True)
class TranslationMemoryValidationResult:
    valid: bool
    record_count: int
    invalid_count: int
    issues: list[str] = field(default_factory=list)


def ensure_translation_memory_file(path: Path) -> bool:
    """Create TM file if missing."""

    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return True


def validate_translation_memory(path: Path) -> TranslationMemoryValidationResult:
    """Validate JSONL translation memory schema."""

    entries, issues = load_translation_memory(path)
    invalid_count = len(issues)
    return TranslationMemoryValidationResult(
        valid=invalid_count == 0,
        record_count=len(entries),
        invalid_count=invalid_count,
        issues=issues,
    )


def load_translation_memory(path: Path) -> tuple[list[TranslationMemoryEntry], list[str]]:
    """Load and validate TM records from JSONL."""

    if not path.exists():
        return [], [f"missing file: {path.name}"]

    entries: list[TranslationMemoryEntry] = []
    issues: list[str] = []

    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            issues.append(f"line {line_no}: invalid JSON")
            continue

        if not isinstance(payload, dict):
            issues.append(f"line {line_no}: expected JSON object")
            continue

        source_text = str(payload.get("source_text", "")).strip()
        target_text = str(payload.get("target_text", "")).strip()
        if not source_text or not target_text:
            issues.append(f"line {line_no}: source_text and target_text are required")
            continue

        entries.append(TranslationMemoryEntry.from_dict(payload))

    return entries, issues


def find_in_translation_memory(path: Path, query: str, limit: int = 10) -> list[TranslationMemoryEntry]:
    """Local case-insensitive lookup in source/target TM fields."""

    needle = query.strip().lower()
    if not needle:
        return []

    entries, _ = load_translation_memory(path)
    matches: list[TranslationMemoryEntry] = []

    for entry in entries:
        haystack = " ".join(
            [
                entry.source_text,
                entry.target_text,
                entry.chapter_id or "",
                entry.chunk_id or "",
                entry.notes or "",
            ]
        ).lower()
        if needle in haystack:
            matches.append(entry)
            if len(matches) >= limit:
                break

    return matches
