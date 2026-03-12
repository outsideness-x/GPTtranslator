"""Workspace path modeling and safe directory provisioning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspacePaths:
    """Resolved top-level workspace layout used by pipeline state."""

    root: Path
    state_path: Path


@dataclass(frozen=True)
class BookWorkspacePaths:
    """Resolved per-book workspace layout."""

    root: Path
    input_dir: Path
    analysis_dir: Path
    memory_dir: Path
    translated_dir: Path
    output_dir: Path
    logs_dir: Path
    manifest_path: Path
    original_pdf_path: Path
    glossary_path: Path
    style_guide_path: Path
    chapter_notes_path: Path
    translation_memory_path: Path

    def directories(self) -> tuple[Path, ...]:
        return (
            self.root,
            self.input_dir,
            self.analysis_dir,
            self.memory_dir,
            self.translated_dir,
            self.output_dir,
            self.logs_dir,
        )

    def seed_files(self) -> tuple[Path, ...]:
        return (
            self.glossary_path,
            self.style_guide_path,
            self.chapter_notes_path,
            self.translation_memory_path,
        )


def resolve_workspace_root(project_root: Path, workspace_dir_name: str) -> Path:
    """Resolve workspace root inside project tree."""

    return (project_root / workspace_dir_name).resolve()


def build_workspace_paths(workspace_root: Path, state_filename: str) -> WorkspacePaths:
    """Build strongly-typed top-level workspace paths."""

    root = workspace_root.resolve()
    return WorkspacePaths(root=root, state_path=root / state_filename)


def ensure_workspace_root(workspace_root: Path) -> Path:
    """Validate and create top-level workspace directory."""

    resolved = workspace_root.resolve()
    _validate_workspace_root(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def build_book_workspace_paths(workspace_root: Path, book_id: str) -> BookWorkspacePaths:
    """Build strongly-typed per-book workspace paths."""

    book_root = (workspace_root / book_id).resolve()
    memory_dir = book_root / "memory"
    input_dir = book_root / "input"
    return BookWorkspacePaths(
        root=book_root,
        input_dir=input_dir,
        analysis_dir=book_root / "analysis",
        memory_dir=memory_dir,
        translated_dir=book_root / "translated",
        output_dir=book_root / "output",
        logs_dir=book_root / "logs",
        manifest_path=book_root / "manifest.json",
        original_pdf_path=input_dir / "original.pdf",
        glossary_path=memory_dir / "glossary.md",
        style_guide_path=memory_dir / "style_guide.md",
        chapter_notes_path=memory_dir / "chapter_notes.md",
        translation_memory_path=memory_dir / "translation_memory.jsonl",
    )


def ensure_book_workspace_layout(paths: BookWorkspacePaths) -> BookWorkspacePaths:
    """Create per-book workspace directories and placeholder memory files."""

    _validate_workspace_root(paths.root)
    for directory in paths.directories():
        directory.mkdir(parents=True, exist_ok=True)

    for file_path in paths.seed_files():
        file_path.touch(exist_ok=True)

    return paths


def _validate_workspace_root(root: Path) -> None:
    resolved = root.resolve()

    if resolved == Path("/") or resolved.parent == resolved:
        raise ValueError("Refusing to use filesystem root as workspace.")

    if len(resolved.parts) < 3:
        raise ValueError(f"Workspace path is too broad: {resolved}")

    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"Workspace root must be a directory: {resolved}")
