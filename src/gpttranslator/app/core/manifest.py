"""Book manifest persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path

from .models import BookManifest


def load_book_manifest(path: Path) -> BookManifest:
    """Load manifest from JSON file."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return BookManifest.from_dict(payload)


def save_book_manifest(path: Path, manifest: BookManifest) -> None:
    """Persist manifest as stable UTF-8 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def create_empty_manifest(book_id: str, source_pdf: str) -> BookManifest:
    """Create empty manifest for a future extraction stage."""

    return BookManifest(book_id=book_id, source_pdf=source_pdf)
