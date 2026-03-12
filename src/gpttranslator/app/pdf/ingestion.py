"""Local PDF ingestion helpers for `init` command."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..core.models import BookManifest
from ..core.paths import (
    BookWorkspacePaths,
    build_book_workspace_paths,
    ensure_book_workspace_layout,
    ensure_workspace_root,
    resolve_workspace_root,
)

PDF_SIGNATURE = b"%PDF-"


class IngestionError(RuntimeError):
    """Raised when local ingestion input or filesystem checks fail."""


@dataclass(frozen=True)
class IngestionResult:
    """Artifacts created by `init` ingestion stage."""

    book_id: str
    workspace_root: Path
    book_workspace: BookWorkspacePaths
    source_pdf: Path
    source_sha256: str


def initialize_book_workspace(
    pdf_path: Path,
    project_root: Path,
    workspace_dir_name: str,
) -> IngestionResult:
    """Validate input PDF and create local workspace scaffold for one book."""

    source_pdf = pdf_path.expanduser().resolve()
    _validate_pdf_candidate(source_pdf)

    sha256 = _sha256_file(source_pdf)
    base_book_id = _build_book_id(source_pdf.stem, sha256)

    workspace_root = ensure_workspace_root(resolve_workspace_root(project_root, workspace_dir_name))
    book_id = _allocate_unique_book_id(workspace_root, base_book_id)
    book_workspace = build_book_workspace_paths(workspace_root, book_id)
    ensure_book_workspace_layout(book_workspace)

    shutil.copy2(source_pdf, book_workspace.original_pdf_path)

    return IngestionResult(
        book_id=book_id,
        workspace_root=workspace_root,
        book_workspace=book_workspace,
        source_pdf=source_pdf,
        source_sha256=sha256,
    )


def create_initial_manifest_payload(result: IngestionResult) -> BookManifest:
    """Create a structured initial manifest for a freshly ingested book."""

    return BookManifest(
        book_id=result.book_id,
        source_pdf="input/original.pdf",
        metadata={
            "stage": "initialized",
            "source_filename": result.source_pdf.name,
            "source_pdf_absolute": str(result.source_pdf),
            "source_sha256": result.source_sha256,
            "workspace": {
                "root": str(result.book_workspace.root),
                "analysis_dir": "analysis",
                "memory_dir": "memory",
                "translated_dir": "translated",
                "output_dir": "output",
                "logs_dir": "logs",
            },
            "pipeline": {
                "inspect": "pending",
                "extract": "pending",
                "translate": "pending",
                "qa": "pending",
                "build": "pending",
            },
        },
    )


def _validate_pdf_candidate(path: Path) -> None:
    if not path.exists():
        raise IngestionError(f"PDF file not found: {path}")

    if not path.is_file():
        raise IngestionError(f"Input path is not a file: {path}")

    if path.suffix.lower() != ".pdf":
        raise IngestionError(f"Input file must use .pdf extension: {path.name}")

    try:
        with path.open("rb") as file:
            signature = file.read(5)
    except OSError as exc:
        raise IngestionError(f"Unable to read input PDF: {path}") from exc

    if signature != PDF_SIGNATURE:
        raise IngestionError(f"Invalid PDF signature in file: {path.name}")


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _build_book_id(stem: str, sha256: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    slug = normalized or "book"
    return f"{slug}-{sha256[:8]}"


def _allocate_unique_book_id(workspace_root: Path, candidate: str) -> str:
    book_id = candidate
    counter = 2

    while (workspace_root / book_id).exists():
        book_id = f"{candidate}-{counter}"
        counter += 1

    return book_id
