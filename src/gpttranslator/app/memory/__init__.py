"""Project-local memory managers: glossary, style guide and translation memory."""

from .glossary_manager import (
    GlossaryEntry,
    GlossaryValidationResult,
    ensure_glossary_template,
    find_in_glossary,
    validate_glossary_structure,
)
from .style_guide_manager import (
    MarkdownValidationResult,
    ensure_chapter_notes_template,
    ensure_style_guide_template,
    validate_chapter_notes_structure,
    validate_style_guide_structure,
)
from .translation_memory_manager import (
    TranslationMemoryEntry,
    TranslationMemoryValidationResult,
    ensure_translation_memory_file,
    find_in_translation_memory,
    validate_translation_memory,
)

__all__ = [
    "GlossaryEntry",
    "GlossaryValidationResult",
    "MarkdownValidationResult",
    "TranslationMemoryEntry",
    "TranslationMemoryValidationResult",
    "ensure_chapter_notes_template",
    "ensure_glossary_template",
    "ensure_style_guide_template",
    "ensure_translation_memory_file",
    "find_in_glossary",
    "find_in_translation_memory",
    "validate_chapter_notes_structure",
    "validate_glossary_structure",
    "validate_style_guide_structure",
]
