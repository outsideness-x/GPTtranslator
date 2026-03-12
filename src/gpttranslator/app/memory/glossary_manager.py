"""Glossary file management and lookups."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_GLOSSARY_HEADINGS: tuple[str, ...] = (
    "# Glossary",
    "## Scope",
    "## Domain Register",
    "## Preferred Terms",
    "## Forbidden Terms",
    "## Term Table",
)


@dataclass(slots=True)
class GlossaryEntry:
    source_term: str
    target_term: str
    part_of_speech: str = ""
    decision: str = ""
    notes: str = ""


@dataclass(slots=True)
class GlossaryValidationResult:
    valid: bool
    term_count: int
    issues: list[str] = field(default_factory=list)


def ensure_glossary_template(path: Path, book_id: str) -> bool:
    """Create publisher-level glossary template when file is missing or empty."""

    if path.exists() and path.read_text(encoding="utf-8").strip():
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_glossary_template(book_id), encoding="utf-8")
    return True


def build_glossary_template(book_id: str) -> str:
    """Build glossary markdown template for editorial-quality projects."""

    return (
        "# Glossary\n\n"
        f"Book ID: `{book_id}`\n\n"
        "## Scope\n"
        "- Fill this glossary with terms that must be translated consistently.\n"
        "- Prefer domain-specific vocabulary over literal word-by-word mapping.\n\n"
        "## Domain Register\n"
        "- Domain: [set subject area]\n"
        "- Audience: [set target audience]\n"
        "- Register: [formal / neutral / conversational]\n\n"
        "## Preferred Terms\n"
        "- Add approved terms with rationale where needed.\n\n"
        "## Forbidden Terms\n"
        "- Add discouraged translations and explain why they are incorrect.\n\n"
        "## Capitalization and Proper Names\n"
        "- Keep organization and product names consistent across chapters.\n\n"
        "## Term Table\n"
        "| Source term | Target term | POS | Decision | Notes |\n"
        "|---|---|---|---|---|\n"
        "| Example term | Example translation | noun | preferred | Keep consistent in headings and body text. |\n"
    )


def validate_glossary_structure(path: Path) -> GlossaryValidationResult:
    """Validate glossary markdown structure and parse term rows."""

    issues: list[str] = []

    if not path.exists():
        return GlossaryValidationResult(valid=False, term_count=0, issues=[f"missing file: {path.name}"])

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        issues.append("glossary is empty")

    for heading in REQUIRED_GLOSSARY_HEADINGS:
        if heading not in text:
            issues.append(f"missing heading: {heading}")

    entries, parse_issues = parse_glossary_entries(path)
    issues.extend(parse_issues)

    return GlossaryValidationResult(valid=not issues, term_count=len(entries), issues=issues)


def parse_glossary_entries(path: Path) -> tuple[list[GlossaryEntry], list[str]]:
    """Parse glossary term table from markdown file."""

    if not path.exists():
        return [], [f"missing file: {path.name}"]

    text = path.read_text(encoding="utf-8")
    lines = _extract_term_table_lines(text)
    if not lines:
        return [], ["term table is missing or empty"]

    entries: list[GlossaryEntry] = []
    issues: list[str] = []

    for line_no, line in lines:
        if not line.strip().startswith("|"):
            continue

        cells = [item.strip() for item in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            issues.append(f"line {line_no}: expected 5+ columns in term table")
            continue

        if _is_header_or_delimiter_row(cells):
            continue

        entry = GlossaryEntry(
            source_term=cells[0],
            target_term=cells[1],
            part_of_speech=cells[2],
            decision=cells[3],
            notes=cells[4],
        )
        if not entry.source_term or not entry.target_term:
            issues.append(f"line {line_no}: source/target term must be non-empty")
            continue
        entries.append(entry)

    return entries, issues


def find_in_glossary(path: Path, query: str, limit: int = 10) -> list[GlossaryEntry]:
    """Local case-insensitive lookup in glossary terms."""

    needle = query.strip().lower()
    if not needle:
        return []

    entries, _ = parse_glossary_entries(path)
    matches: list[GlossaryEntry] = []
    for entry in entries:
        haystack = " ".join(
            [
                entry.source_term,
                entry.target_term,
                entry.part_of_speech,
                entry.decision,
                entry.notes,
            ]
        ).lower()
        if needle in haystack:
            matches.append(entry)
            if len(matches) >= limit:
                break
    return matches


def _extract_term_table_lines(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    start: int | None = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == "## term table":
            start = idx + 1
            break

    if start is None:
        return []

    rows: list[tuple[int, str]] = []
    for idx in range(start, len(lines)):
        line = lines[idx]
        if line.startswith("## "):
            break
        if line.strip():
            rows.append((idx + 1, line))
    return rows


def _is_header_or_delimiter_row(cells: list[str]) -> bool:
    lowered = [cell.lower() for cell in cells]
    if lowered[:2] == ["source term", "target term"]:
        return True
    if all(set(cell) <= {"-", ":"} for cell in cells if cell):
        return True
    return False
