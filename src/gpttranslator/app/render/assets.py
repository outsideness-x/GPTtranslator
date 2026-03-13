"""Image asset extraction/copy stage for PDF build."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader


@dataclass(frozen=True, slots=True)
class AssetCopyRecord:
    """One expected image asset extraction result."""

    image_id: str
    page_num: int
    status: str
    asset_path: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "page_num": self.page_num,
            "status": self.status,
            "asset_path": self.asset_path,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class AssetBundle:
    """Collected image assets and extraction diagnostics."""

    assets_dir: Path
    manifest_path: Path
    records: tuple[AssetCopyRecord, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def copied_count(self) -> int:
        return sum(1 for item in self.records if item.status == "copied")

    @property
    def missing_count(self) -> int:
        return sum(1 for item in self.records if item.status != "copied")


class AssetCollectionError(RuntimeError):
    """Raised when image assets cannot be collected."""


def collect_image_assets(book_root: Path) -> AssetBundle:
    """Extract image bytes from source PDF into `output/assets` directory."""

    source_pdf_path = book_root / "input" / "original.pdf"
    images_path = book_root / "analysis" / "images.jsonl"

    if not source_pdf_path.exists():
        raise AssetCollectionError(f"source PDF not found: {source_pdf_path}")

    assets_dir = book_root / "output" / "assets"
    manifest_path = book_root / "output" / "assets_manifest.jsonl"
    assets_dir.mkdir(parents=True, exist_ok=True)

    expected_rows = _load_jsonl(images_path)
    if not expected_rows:
        manifest_path.write_text("", encoding="utf-8")
        return AssetBundle(
            assets_dir=assets_dir,
            manifest_path=manifest_path,
            records=tuple(),
            warnings=tuple(),
        )

    try:
        reader = PdfReader(str(source_pdf_path))
    except Exception as exc:  # pragma: no cover - pypdf backend error handling
        raise AssetCollectionError(f"unable to read source PDF for assets: {exc}") from exc

    expected_rows = sorted(
        expected_rows,
        key=lambda item: (
            int(item.get("page_num", 0)),
            str(item.get("image_id", "")),
        ),
    )

    records: list[AssetCopyRecord] = []
    warnings: list[str] = []

    page_images_cache: dict[int, list[Any]] = {}
    page_index_offsets: dict[int, int] = {}

    for row in expected_rows:
        image_id = str(row.get("image_id", "")).strip()
        page_num = int(row.get("page_num", 0) or 0)
        object_name = str(row.get("object_name", "")).strip()
        if not image_id or page_num < 1:
            continue

        if page_num not in page_images_cache:
            page_images_cache[page_num] = _page_images(reader, page_num)
            page_index_offsets[page_num] = 0

        page_images = page_images_cache[page_num]
        expected_norm_name = _normalize_object_name(object_name)

        selected = _match_page_image(
            page_images=page_images,
            expected_norm_name=expected_norm_name,
            start_offset=page_index_offsets.get(page_num, 0),
        )

        if selected is None:
            record = AssetCopyRecord(
                image_id=image_id,
                page_num=page_num,
                status="missing",
                asset_path="",
                message="image object was not found on source page",
            )
            records.append(record)
            warnings.append(f"image {image_id}: not found on page {page_num}")
            continue

        selected_index, selected_image = selected
        page_index_offsets[page_num] = selected_index + 1

        raw_bytes = _image_bytes(selected_image)
        if not raw_bytes:
            record = AssetCopyRecord(
                image_id=image_id,
                page_num=page_num,
                status="missing",
                asset_path="",
                message="image bytes are unavailable",
            )
            records.append(record)
            warnings.append(f"image {image_id}: extracted object has no bytes")
            continue

        ext = _guess_extension(selected_image, row)
        target_path = assets_dir / f"{image_id}{ext}"
        target_path.write_bytes(raw_bytes)

        records.append(
            AssetCopyRecord(
                image_id=image_id,
                page_num=page_num,
                status="copied",
                asset_path=str(target_path),
            )
        )

    manifest_path.write_text("", encoding="utf-8")
    with manifest_path.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    return AssetBundle(
        assets_dir=assets_dir,
        manifest_path=manifest_path,
        records=tuple(records),
        warnings=tuple(warnings),
    )


def _page_images(reader: PdfReader, page_num: int) -> list[Any]:
    index = page_num - 1
    if index < 0 or index >= len(reader.pages):
        return []

    page = reader.pages[index]
    try:
        return list(page.images)
    except Exception:
        return []


def _match_page_image(
    *,
    page_images: list[Any],
    expected_norm_name: str,
    start_offset: int,
) -> tuple[int, Any] | None:
    if not page_images:
        return None

    if expected_norm_name:
        for idx, candidate in enumerate(page_images):
            candidate_name = _normalize_object_name(str(getattr(candidate, "name", "")))
            if candidate_name and candidate_name == expected_norm_name:
                return idx, candidate

    if 0 <= start_offset < len(page_images):
        return start_offset, page_images[start_offset]

    return None


def _image_bytes(image_obj: Any) -> bytes:
    data = getattr(image_obj, "data", None)
    if callable(data):
        try:
            data = data()
        except Exception:
            data = None
    if isinstance(data, bytes):
        return data
    return b""


def _guess_extension(image_obj: Any, expected_row: dict[str, Any]) -> str:
    name = str(getattr(image_obj, "name", "")).strip()
    suffix = Path(name).suffix.lower()
    if suffix:
        return suffix

    filters = expected_row.get("filters")
    if isinstance(filters, list):
        lowered = " ".join(str(item).lower() for item in filters)
        if "dct" in lowered or "jpeg" in lowered:
            return ".jpg"
        if "jp" in lowered:
            return ".jp2"
        if "flate" in lowered:
            return ".png"

    return ".bin"


def _normalize_object_name(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace("/", "")
    normalized = normalized.replace(" ", "")
    return normalized


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows
