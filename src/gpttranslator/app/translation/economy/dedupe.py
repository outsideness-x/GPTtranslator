"""Content fingerprinting and job-cache deduplication utilities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.models import Chunk
from ..protocol import load_and_validate_output_json
from .context import ContextPackage


@dataclass(frozen=True, slots=True)
class JobCacheRecord:
    """Stored job output metadata for content-based reuse."""

    fingerprint: str
    template_id: str
    output_path: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "fingerprint": self.fingerprint,
            "template_id": self.template_id,
            "output_path": self.output_path,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobCacheRecord":
        return cls(
            fingerprint=str(data.get("fingerprint", "")),
            template_id=str(data.get("template_id", "translate_chunk")),
            output_path=str(data.get("output_path", "")),
            created_at=str(data.get("created_at", "")),
        )


def build_content_fingerprint(
    *,
    chunk: Chunk,
    context_package: ContextPackage,
    profile_name: str,
    template_id: str,
    template_version: int,
) -> str:
    """Build deterministic fingerprint for job-dedup cache lookups."""

    payload = {
        "chunk_id": chunk.chunk_id,
        "chapter_id": chunk.chapter_id,
        "source_text": chunk.source_text,
        "block_ids": chunk.block_ids,
        "footnote_refs": chunk.footnote_refs,
        "profile": profile_name,
        "template_id": template_id,
        "template_version": template_version,
        "context": context_package.to_compact_payload(),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_job_cache(path: Path) -> dict[str, JobCacheRecord]:
    """Load fingerprint cache from JSON file."""

    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    if not isinstance(payload, dict):
        return {}

    cache: dict[str, JobCacheRecord] = {}
    for key, raw_value in payload.items():
        if not isinstance(raw_value, dict):
            continue
        record = JobCacheRecord.from_dict(raw_value)
        if record.fingerprint and record.output_path:
            cache[key] = record

    return cache


def save_job_cache(path: Path, cache: dict[str, JobCacheRecord]) -> None:
    """Persist fingerprint cache as stable JSON."""

    serialized = {key: record.to_dict() for key, record in cache.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_cache_hit(
    *,
    cache: dict[str, JobCacheRecord],
    fingerprint: str,
    expected_job_id: str | None,
    expected_template_id: str,
) -> Path | None:
    """Return cached output path when cached JSON is still valid."""

    record = cache.get(fingerprint)
    if record is None:
        return None

    if record.template_id != expected_template_id:
        return None

    output_path = Path(record.output_path)
    if not output_path.exists():
        return None

    validation = load_and_validate_output_json(
        output_path,
        expected_job_id=expected_job_id,
        expected_template_id=expected_template_id,
    )
    if validation.payload is None:
        return None

    return output_path


def update_cache_record(
    *,
    cache: dict[str, JobCacheRecord],
    fingerprint: str,
    template_id: str,
    output_path: Path,
    created_at: str,
) -> None:
    """Insert or overwrite cache entry for one fingerprint."""

    cache[fingerprint] = JobCacheRecord(
        fingerprint=fingerprint,
        template_id=template_id,
        output_path=str(output_path),
        created_at=created_at,
    )
