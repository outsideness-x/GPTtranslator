"""Style guide and chapter notes management."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_STYLE_GUIDE_HEADINGS: tuple[str, ...] = (
    "# Style Guide",
    "## Voice and Tone",
    "## Register and Audience",
    "## Terminology Rules",
    "## Numbers, Dates and Units",
    "## Punctuation and Quotes",
    "## Proper Names and Transliteration",
    "## Formatting Rules",
    "## QA Checklist",
)

REQUIRED_CHAPTER_NOTES_HEADINGS: tuple[str, ...] = (
    "# Chapter Notes",
    "## Global Notes",
)


@dataclass(slots=True)
class MarkdownValidationResult:
    valid: bool
    issues: list[str] = field(default_factory=list)


def ensure_style_guide_template(path: Path, book_id: str) -> bool:
    """Create style guide template if file is missing or empty."""

    if path.exists() and path.read_text(encoding="utf-8").strip():
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_style_guide_template(book_id), encoding="utf-8")
    return True


def build_style_guide_template(book_id: str) -> str:
    return (
        "# Style Guide\n\n"
        f"Book ID: `{book_id}`\n\n"
        "## Voice and Tone\n"
        "- Define narrative voice, emotional intensity, and sentence rhythm.\n\n"
        "## Register and Audience\n"
        "- Specify formality level and readability target.\n\n"
        "## Terminology Rules\n"
        "- Keep glossary-preferred terms mandatory across all chapters.\n\n"
        "## Numbers, Dates and Units\n"
        "- Define localized conventions and when to keep source format.\n\n"
        "## Punctuation and Quotes\n"
        "- Choose quote marks, dash rules, and punctuation spacing conventions.\n\n"
        "## Proper Names and Transliteration\n"
        "- Document accepted transliteration rules and protected names.\n\n"
        "## Formatting Rules\n"
        "- Define handling of italics, bold, abbreviations, and lists.\n\n"
        "## QA Checklist\n"
        "- Check consistency with glossary and chapter notes.\n"
        "- Check sentence completeness and punctuation correctness.\n"
    )


def validate_style_guide_structure(path: Path) -> MarkdownValidationResult:
    """Validate style guide markdown headings."""

    if not path.exists():
        return MarkdownValidationResult(valid=False, issues=[f"missing file: {path.name}"])

    text = path.read_text(encoding="utf-8")
    issues: list[str] = []
    if not text.strip():
        issues.append("style guide is empty")

    for heading in REQUIRED_STYLE_GUIDE_HEADINGS:
        if heading not in text:
            issues.append(f"missing heading: {heading}")

    return MarkdownValidationResult(valid=not issues, issues=issues)


def ensure_chapter_notes_template(path: Path, book_id: str) -> bool:
    """Create chapter notes template if file is missing or empty."""

    if path.exists() and path.read_text(encoding="utf-8").strip():
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_chapter_notes_template(book_id), encoding="utf-8")
    return True


def build_chapter_notes_template(book_id: str) -> str:
    return (
        "# Chapter Notes\n\n"
        f"Book ID: `{book_id}`\n\n"
        "## Global Notes\n"
        "- Add constraints that affect all chapters.\n\n"
        "## Chapter 01\n"
        "- Tone:\n"
        "- Terminology risks:\n"
        "- Open questions:\n"
    )


def validate_chapter_notes_structure(path: Path) -> MarkdownValidationResult:
    """Validate chapter notes file presence and basic structure."""

    if not path.exists():
        return MarkdownValidationResult(valid=False, issues=[f"missing file: {path.name}"])

    text = path.read_text(encoding="utf-8")
    issues: list[str] = []
    if not text.strip():
        issues.append("chapter notes are empty")

    for heading in REQUIRED_CHAPTER_NOTES_HEADINGS:
        if heading not in text:
            issues.append(f"missing heading: {heading}")

    return MarkdownValidationResult(valid=not issues, issues=issues)
