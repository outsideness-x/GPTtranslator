"""Editorial pass over translated chunks using Codex backend."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from ..core.models import Chunk
from ..memory.glossary_manager import GlossaryEntry
from ..memory.glossary_manager import parse_glossary_entries
from .codex_backend import ChunkTranslationRequest
from .economy.context import slice_glossary_entries
from .protocol import utcnow_iso

RewriteLevel = Literal["light", "medium", "aggressive"]
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class EditorialOptions:
    """Settings controlling codex editorial pass behavior."""

    strict_terminology: bool = True
    preserve_literalness: bool = False
    rewrite_level: RewriteLevel = "medium"
    resume: bool = False


@dataclass(frozen=True, slots=True)
class EditorialResult:
    """Summary of editorial stage execution."""

    edited_chunks_path: Path
    codex_jobs_log_path: Path
    codex_failures_log_path: Path
    total_chunks: int
    processed_chunks: int
    edited_chunks: int
    failed_chunks: int
    skipped_chunks: int
    elapsed_seconds: float


def run_editorial_pass(
    *,
    book_root: Path,
    backend: Any,
    options: EditorialOptions,
    progress_callback: ProgressCallback | None = None,
) -> EditorialResult:
    """Run Codex editorial pass over completed translated chunks."""

    translated_chunks_path = book_root / "translated" / "translated_chunks.jsonl"
    edited_chunks_path = book_root / "translated" / "edited_chunks.jsonl"
    codex_jobs_log_path = book_root / "logs" / "codex_jobs.jsonl"
    codex_failures_log_path = book_root / "logs" / "codex_failures.jsonl"
    chunks_map = _load_chunks_map(book_root / "analysis" / "chunks.jsonl")

    style_guide = _safe_read_text(book_root / "memory" / "style_guide.md")
    chapter_notes = _safe_read_text(book_root / "memory" / "chapter_notes.md")
    glossary_entries, _ = parse_glossary_entries(book_root / "memory" / "glossary.md")

    translated_rows = _load_jsonl(translated_chunks_path)
    completed_rows = [row for row in translated_rows if str(row.get("status", "")) == "completed"]

    already_edited_ids: set[str] = set()
    if options.resume:
        for row in _load_jsonl(edited_chunks_path):
            if str(row.get("status", "")) == "completed":
                already_edited_ids.add(str(row.get("chunk_id", "")))
    else:
        edited_chunks_path.write_text("", encoding="utf-8")

    started_at = time.monotonic()
    total = len(completed_rows)
    processed = 0
    edited = 0
    failed = 0
    skipped = 0

    for row in completed_rows:
        chunk_id = str(row.get("chunk_id", ""))
        if not chunk_id:
            continue

        if chunk_id in already_edited_ids:
            skipped += 1
            continue

        chunk = chunks_map.get(chunk_id)
        if chunk is None:
            source_text = str(row.get("source_text", ""))
            chunk = Chunk(
                chunk_id=chunk_id,
                chapter_id=str(row.get("chapter_id", "")) or None,
                page_range=(1, 1),
                block_ids=[str(item) for item in row.get("block_ids", []) if isinstance(item, str)],
                chunk_type="paragraph_group",
                source_text=source_text,
            )

        current_translation = str(row.get("target_text", ""))
        glossary_subset = _build_glossary_subset(chunk.source_text, glossary_entries)

        request = ChunkTranslationRequest(
            workspace_root=book_root.parent,
            book_id=book_root.name,
            chunk=chunk,
            glossary=glossary_subset,
            style_hints=[
                f"strict_terminology={str(options.strict_terminology).lower()}",
                f"preserve_literalness={str(options.preserve_literalness).lower()}",
                f"editorial_rewrite_level={options.rewrite_level}",
            ],
            style_guide=style_guide,
            chapter_notes=chapter_notes,
            translated_text=current_translation,
            strict_terminology=options.strict_terminology,
            preserve_literalness=options.preserve_literalness,
            editorial_rewrite_level=options.rewrite_level,
            template_id="editorial_pass",
            job_id=f"editorial-{chunk_id}",
        )

        translated = backend.translate_chunk(request)
        processed += 1
        timestamp = utcnow_iso()
        job_row = {
            "stage": "editorial",
            "book_id": book_root.name,
            "chunk_id": chunk_id,
            "job_id": translated.job.job_id,
            "success": translated.result.success,
            "return_code": translated.result.return_code,
            "attempt_count": translated.result.attempt_count,
            "output_path": translated.result.output_path or "",
            "failure_reason": translated.result.failure_reason or "",
            "updated_at": timestamp,
        }
        _append_jsonl(codex_jobs_log_path, job_row)

        if translated.result.success and translated.output_payload is not None:
            edited_text = str(translated.output_payload.get("edited_text", ""))
            if edited_text.strip():
                edited += 1
                _append_jsonl(
                    edited_chunks_path,
                    {
                        "chunk_id": chunk_id,
                        "chapter_id": chunk.chapter_id or "",
                        "status": "completed",
                        "source": "editorial_pass",
                        "target_text": edited_text,
                        "original_target_text": current_translation,
                        "job_id": translated.job.job_id,
                        "output_path": translated.result.output_path or "",
                        "updated_at": timestamp,
                    },
                )
            else:
                failed += 1
                failure_row = {
                    "stage": "editorial",
                    "book_id": book_root.name,
                    "chunk_id": chunk_id,
                    "job_id": translated.job.job_id,
                    "failure_reason": "empty_edited_text",
                    "updated_at": timestamp,
                }
                _append_jsonl(codex_failures_log_path, failure_row)
                _append_jsonl(
                    edited_chunks_path,
                    {
                        "chunk_id": chunk_id,
                        "chapter_id": chunk.chapter_id or "",
                        "status": "failed",
                        "source": "editorial_pass",
                        "target_text": current_translation,
                        "original_target_text": current_translation,
                        "job_id": translated.job.job_id,
                        "output_path": translated.result.output_path or "",
                        "error": "empty_edited_text",
                        "updated_at": timestamp,
                    },
                )
        else:
            failed += 1
            failure_reason = translated.result.failure_reason or translated.result.stderr or "editorial_failed"
            _append_jsonl(
                codex_failures_log_path,
                {
                    "stage": "editorial",
                    "book_id": book_root.name,
                    "chunk_id": chunk_id,
                    "job_id": translated.job.job_id,
                    "failure_reason": failure_reason,
                    "updated_at": timestamp,
                },
            )
            _append_jsonl(
                edited_chunks_path,
                {
                    "chunk_id": chunk_id,
                    "chapter_id": chunk.chapter_id or "",
                    "status": "failed",
                    "source": "editorial_pass",
                    "target_text": current_translation,
                    "original_target_text": current_translation,
                    "job_id": translated.job.job_id,
                    "output_path": translated.result.output_path or "",
                    "error": failure_reason,
                    "updated_at": timestamp,
                },
            )

        _emit_progress(
            progress_callback=progress_callback,
            processed=processed,
            total=max(1, total),
            edited=edited,
            failed=failed,
            skipped=skipped,
            started_at=started_at,
        )

    elapsed_seconds = max(0.0, time.monotonic() - started_at)
    return EditorialResult(
        edited_chunks_path=edited_chunks_path,
        codex_jobs_log_path=codex_jobs_log_path,
        codex_failures_log_path=codex_failures_log_path,
        total_chunks=total,
        processed_chunks=processed,
        edited_chunks=edited,
        failed_chunks=failed,
        skipped_chunks=skipped,
        elapsed_seconds=elapsed_seconds,
    )


def _build_glossary_subset(source_text: str, glossary_entries: list[GlossaryEntry]) -> list[dict[str, str]]:
    if not source_text.strip() or not glossary_entries:
        return []
    exact, fuzzy = slice_glossary_entries(
        source_text,
        glossary_entries,
        max_exact=16,
        max_fuzzy=8,
    )
    selected = [*exact, *fuzzy]
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in selected:
        source = item.source_term.strip()
        target = item.target_term.strip()
        if not source or not target:
            continue
        key = source.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append({"source": source, "target": target, "note": item.notes})
    return result


def _load_chunks_map(path: Path) -> dict[str, Chunk]:
    rows = _load_jsonl(path)
    mapping: dict[str, Chunk] = {}
    for row in rows:
        if isinstance(row, dict) and "chunk_id" in row:
            chunk = Chunk.from_dict(row)
            mapping[chunk.chunk_id] = chunk
    return mapping


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


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _safe_read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _emit_progress(
    *,
    progress_callback: ProgressCallback | None,
    processed: int,
    total: int,
    edited: int,
    failed: int,
    skipped: int,
    started_at: float,
) -> None:
    if progress_callback is None:
        return
    elapsed = max(0.0, time.monotonic() - started_at)
    eta_seconds = 0.0
    if processed > 0 and total > processed:
        eta_seconds = (elapsed / processed) * (total - processed)
    progress_callback(
        f"Editorial {processed}/{total} | edited={edited} failed={failed} skipped={skipped} "
        f"| elapsed={_format_duration(elapsed)} eta={_format_duration(eta_seconds)}"
    )


def _format_duration(seconds: float) -> str:
    whole = int(max(0.0, seconds))
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
