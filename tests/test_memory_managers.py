"""Unit tests for local memory managers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.memory.glossary_manager import (
    ensure_glossary_template,
    find_in_glossary,
    validate_glossary_structure,
)
from gpttranslator.app.memory.style_guide_manager import (
    ensure_chapter_notes_template,
    ensure_style_guide_template,
    validate_chapter_notes_structure,
    validate_style_guide_structure,
)
from gpttranslator.app.memory.translation_memory_manager import (
    ensure_translation_memory_file,
    find_in_translation_memory,
    validate_translation_memory,
)


def test_glossary_template_validation_and_search(tmp_path: Path) -> None:
    glossary_path = tmp_path / "glossary.md"

    created = ensure_glossary_template(glossary_path, "book-001")
    assert created is True

    validation = validate_glossary_structure(glossary_path)
    assert validation.valid is True
    assert validation.term_count >= 1

    matches = find_in_glossary(glossary_path, "example")
    assert matches
    assert matches[0].target_term


def test_style_guide_and_chapter_notes_templates_are_valid(tmp_path: Path) -> None:
    style_path = tmp_path / "style_guide.md"
    notes_path = tmp_path / "chapter_notes.md"

    assert ensure_style_guide_template(style_path, "book-001") is True
    assert ensure_chapter_notes_template(notes_path, "book-001") is True

    style_validation = validate_style_guide_structure(style_path)
    notes_validation = validate_chapter_notes_structure(notes_path)

    assert style_validation.valid is True
    assert notes_validation.valid is True


def test_translation_memory_validation_and_search(tmp_path: Path) -> None:
    tm_path = tmp_path / "translation_memory.jsonl"
    assert ensure_translation_memory_file(tm_path) is True

    rows = [
        {"source_text": "Machine learning", "target_text": "Machine learning", "chapter_id": "ch-01"},
        {"source_text": "Neural network", "target_text": "Neural network", "chapter_id": "ch-01"},
    ]
    tm_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    validation = validate_translation_memory(tm_path)
    assert validation.valid is True
    assert validation.record_count == 2

    matches = find_in_translation_memory(tm_path, "neural")
    assert len(matches) == 1
    assert matches[0].target_text == "Neural network"
