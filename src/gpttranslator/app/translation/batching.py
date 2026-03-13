"""Batch processing and resume orchestration for long-book translation."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, cast

from .codex_backend import ChunkTranslationRequest
from .economy.planner import ChunkPlan
from .protocol import load_and_validate_output_json, utcnow_iso

BATCH_MANIFEST_SCHEMA_VERSION = "gpttranslator.translation.batch_manifest.v1"
CHECKPOINT_SCHEMA_VERSION = "gpttranslator.translation.checkpoint.v1"

BatchStatus = Literal["pending", "running", "completed", "failed"]
CheckpointStatus = Literal["pending", "completed", "failed", "skipped"]

ProgressCallback = Callable[[str], None]


@dataclass(slots=True)
class BatchRecord:
    """Execution state for one chunk batch."""

    batch_id: str
    chunk_ids: list[str]
    status: BatchStatus = "pending"
    attempts: int = 0
    last_error: str = ""
    started_at: str = ""
    finished_at: str = ""
    completed_chunk_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "chunk_ids": self.chunk_ids,
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "completed_chunk_ids": self.completed_chunk_ids,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BatchRecord":
        return cls(
            batch_id=str(payload.get("batch_id", "")),
            chunk_ids=[str(item) for item in payload.get("chunk_ids", [])],
            status=_coerce_batch_status(payload.get("status", "pending")),
            attempts=int(payload.get("attempts", 0)),
            last_error=str(payload.get("last_error", "")),
            started_at=str(payload.get("started_at", "")),
            finished_at=str(payload.get("finished_at", "")),
            completed_chunk_ids=[str(item) for item in payload.get("completed_chunk_ids", [])],
        )


@dataclass(slots=True)
class BatchManifest:
    """Book-level batch execution manifest."""

    schema_version: str
    book_id: str
    strategy: str
    created_at: str
    updated_at: str
    batches: list[BatchRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "book_id": self.book_id,
            "strategy": self.strategy,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "batches": [item.to_dict() for item in self.batches],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BatchManifest":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            book_id=str(payload.get("book_id", "")),
            strategy=str(payload.get("strategy", "")),
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at", "")),
            batches=[BatchRecord.from_dict(item) for item in payload.get("batches", []) if isinstance(item, dict)],
        )


@dataclass(slots=True)
class ChunkCheckpoint:
    """Persisted chunk-level status for resume support."""

    chunk_id: str
    batch_id: str
    status: CheckpointStatus
    source: str
    attempts: int = 0
    job_id: str = ""
    output_path: str = ""
    target_text: str = ""
    last_error: str = ""
    updated_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "batch_id": self.batch_id,
            "status": self.status,
            "source": self.source,
            "attempts": self.attempts,
            "job_id": self.job_id,
            "output_path": self.output_path,
            "target_text": self.target_text,
            "last_error": self.last_error,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChunkCheckpoint":
        return cls(
            chunk_id=str(payload.get("chunk_id", "")),
            batch_id=str(payload.get("batch_id", "")),
            status=_coerce_checkpoint_status(payload.get("status", "pending")),
            source=str(payload.get("source", "")),
            attempts=int(payload.get("attempts", 0)),
            job_id=str(payload.get("job_id", "")),
            output_path=str(payload.get("output_path", "")),
            target_text=str(payload.get("target_text", "")),
            last_error=str(payload.get("last_error", "")),
            updated_at=str(payload.get("updated_at", utcnow_iso())),
        )


@dataclass(slots=True)
class TranslationCheckpoint:
    """Book-level checkpoint map keyed by chunk_id."""

    schema_version: str
    book_id: str
    created_at: str
    updated_at: str
    chunks: dict[str, ChunkCheckpoint]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "book_id": self.book_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "chunks": {key: value.to_dict() for key, value in self.chunks.items()},
        }

    @classmethod
    def empty(cls, book_id: str) -> "TranslationCheckpoint":
        now = utcnow_iso()
        return cls(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            book_id=book_id,
            created_at=now,
            updated_at=now,
            chunks={},
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TranslationCheckpoint":
        raw_chunks = payload.get("chunks", {})
        chunks: dict[str, ChunkCheckpoint] = {}
        if isinstance(raw_chunks, dict):
            for chunk_id, item in raw_chunks.items():
                if isinstance(item, dict):
                    chunks[str(chunk_id)] = ChunkCheckpoint.from_dict(item)
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            book_id=str(payload.get("book_id", "")),
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at", utcnow_iso())),
            chunks=chunks,
        )


@dataclass(frozen=True, slots=True)
class BatchRunOptions:
    """User-facing flags controlling batch processing behavior."""

    resume: bool = False
    from_batch: str | None = None
    to_batch: str | None = None
    only_failed: bool = False
    max_chunks_per_batch: int = 24


@dataclass(frozen=True, slots=True)
class BatchRunResult:
    """Aggregate result of batch execution stage."""

    manifest_path: Path
    checkpoint_path: Path
    selected_batch_ids: tuple[str, ...]
    total_target_chunks: int
    processed_chunks: int
    completed_chunks: int
    failed_chunks: int
    skipped_chunks: int
    elapsed_seconds: float
    translated_chunks_path: Path
    codex_jobs_log_path: Path
    codex_failures_log_path: Path


@dataclass(frozen=True, slots=True)
class ChunkHandleResult:
    """Structured chunk execution outcome."""

    checkpoint: ChunkCheckpoint
    translated_chunk_row: dict[str, Any] | None = None
    codex_job_row: dict[str, Any] | None = None
    codex_failure_row: dict[str, Any] | None = None


def build_batch_manifest(
    *,
    book_id: str,
    plans: list[ChunkPlan],
    max_chunks_per_batch: int,
) -> BatchManifest:
    """Build deterministic batch manifest grouped by chapter, then by chunk ranges."""

    if max_chunks_per_batch < 1:
        raise ValueError("max_chunks_per_batch must be >= 1")

    ordered_groups: list[tuple[str, list[str]]] = []
    current_key = ""
    current_ids: list[str] = []

    for plan in plans:
        chapter = (plan.chunk.chapter_id or "").strip() or "__range__"
        if not current_ids:
            current_key = chapter
            current_ids = [plan.chunk.chunk_id]
            continue
        if chapter == current_key:
            current_ids.append(plan.chunk.chunk_id)
            continue
        ordered_groups.append((current_key, current_ids))
        current_key = chapter
        current_ids = [plan.chunk.chunk_id]

    if current_ids:
        ordered_groups.append((current_key, current_ids))

    batches: list[BatchRecord] = []
    batch_index = 1
    for key, chunk_ids in ordered_groups:
        for offset in range(0, len(chunk_ids), max_chunks_per_batch):
            slice_ids = chunk_ids[offset : offset + max_chunks_per_batch]
            slug = key if key != "__range__" else "range"
            batch_id = f"batch-{batch_index:04d}-{_slugify(slug)}"
            batches.append(BatchRecord(batch_id=batch_id, chunk_ids=slice_ids))
            batch_index += 1

    now = utcnow_iso()
    return BatchManifest(
        schema_version=BATCH_MANIFEST_SCHEMA_VERSION,
        book_id=book_id,
        strategy="chapter_then_chunk_range",
        created_at=now,
        updated_at=now,
        batches=batches,
    )


def save_batch_manifest(path: Path, manifest: BatchManifest) -> None:
    """Persist batch manifest with stable formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_batch_manifest(path: Path) -> BatchManifest:
    """Load batch manifest from filesystem."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("batch manifest root must be an object")
    manifest = BatchManifest.from_dict(payload)
    if manifest.schema_version != BATCH_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported batch manifest schema version")
    return manifest


def load_checkpoint(path: Path, *, book_id: str) -> TranslationCheckpoint:
    """Load existing checkpoint or return empty checkpoint."""

    if not path.exists():
        return TranslationCheckpoint.empty(book_id=book_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return TranslationCheckpoint.empty(book_id=book_id)
    checkpoint = TranslationCheckpoint.from_dict(payload)
    if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
        return TranslationCheckpoint.empty(book_id=book_id)
    return checkpoint


def save_checkpoint(path: Path, checkpoint: TranslationCheckpoint) -> None:
    """Persist checkpoint JSON for resume."""

    checkpoint.updated_at = utcnow_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checkpoint.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def select_batches_for_run(
    *,
    manifest: BatchManifest,
    options: BatchRunOptions,
) -> list[BatchRecord]:
    """Select batches using resume/from/to/only-failed filters."""

    selected = list(manifest.batches)
    if options.from_batch:
        start_index = _find_batch_index(selected, options.from_batch)
        selected = selected[start_index:]
    if options.to_batch:
        end_index = _find_batch_index(selected, options.to_batch)
        selected = selected[: end_index + 1]

    if options.only_failed:
        return [item for item in selected if item.status == "failed"]
    if options.resume:
        return [item for item in selected if item.status in {"pending", "failed", "running"}]
    return selected


def run_batch_translation(
    *,
    book_id: str,
    plans: list[ChunkPlan],
    translated_dir: Path,
    logs_dir: Path,
    backend: Any,
    options: BatchRunOptions,
    timeout_seconds: int,
    max_attempts: int,
    strict_json: bool,
    progress_callback: ProgressCallback | None = None,
) -> BatchRunResult:
    """Run chunk translation in resumable batches with per-chunk checkpoints."""

    if not hasattr(backend, "translate_chunk"):
        raise ValueError("backend must provide translate_chunk(request)")

    plan_by_chunk_id = {plan.chunk.chunk_id: plan for plan in plans}
    if len(plan_by_chunk_id) != len(plans):
        raise ValueError("chunk ids must be unique within one run")

    manifest_path = translated_dir / "batch_manifest.json"
    checkpoint_path = translated_dir / "chunk_checkpoints.json"
    translated_chunks_path = translated_dir / "translated_chunks.jsonl"
    codex_jobs_log_path = logs_dir / "codex_jobs.jsonl"
    codex_failures_log_path = logs_dir / "codex_failures.jsonl"
    chunks_dir = translated_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = translated_dir.parent.parent

    if not options.resume:
        translated_chunks_path.write_text("", encoding="utf-8")
        codex_jobs_log_path.write_text("", encoding="utf-8")
        codex_failures_log_path.write_text("", encoding="utf-8")

    if options.resume and manifest_path.exists():
        manifest = load_batch_manifest(manifest_path)
    else:
        manifest = build_batch_manifest(
            book_id=book_id,
            plans=plans,
            max_chunks_per_batch=options.max_chunks_per_batch,
        )
        save_batch_manifest(manifest_path, manifest)

    checkpoint = (
        load_checkpoint(checkpoint_path, book_id=book_id)
        if options.resume
        else TranslationCheckpoint.empty(book_id=book_id)
    )
    if not options.resume:
        save_checkpoint(checkpoint_path, checkpoint)

    selected_batches = select_batches_for_run(manifest=manifest, options=options)
    selected_batch_ids = tuple(item.batch_id for item in selected_batches)
    total_target_chunks = _count_target_chunks(selected_batches, checkpoint)

    started_at = time.monotonic()
    processed_chunks = 0
    completed_chunks = 0
    failed_chunks = 0
    skipped_chunks = 0

    for batch in selected_batches:
        batch.status = "running"
        batch.attempts += 1
        batch.last_error = ""
        batch.started_at = batch.started_at or utcnow_iso()
        batch.finished_at = ""
        manifest.updated_at = utcnow_iso()
        save_batch_manifest(manifest_path, manifest)

        for chunk_id in batch.chunk_ids:
            plan = plan_by_chunk_id.get(chunk_id)
            if plan is None:
                failed_chunks += 1
                batch.last_error = f"chunk plan is missing: {chunk_id}"
                checkpoint.chunks[chunk_id] = ChunkCheckpoint(
                    chunk_id=chunk_id,
                    batch_id=batch.batch_id,
                    status="failed",
                    source="planner",
                    attempts=batch.attempts,
                    last_error=batch.last_error,
                )
                save_checkpoint(checkpoint_path, checkpoint)
                continue

            existing = checkpoint.chunks.get(chunk_id)
            if existing is not None and existing.status == "completed":
                skipped_chunks += 1
                if chunk_id not in batch.completed_chunk_ids:
                    batch.completed_chunk_ids.append(chunk_id)
                continue

            handled = _handle_chunk(
                book_id=book_id,
                workspace_root=workspace_root,
                batch_id=batch.batch_id,
                chunk_plan=plan,
                translated_dir=translated_dir,
                backend=backend,
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
                strict_json=strict_json,
            )
            checkpoint.chunks[chunk_id] = handled.checkpoint
            save_checkpoint(checkpoint_path, checkpoint)
            _append_optional_jsonl(translated_chunks_path, handled.translated_chunk_row)
            _append_optional_jsonl(codex_jobs_log_path, handled.codex_job_row)
            _append_optional_jsonl(codex_failures_log_path, handled.codex_failure_row)

            processed_chunks += 1
            if handled.checkpoint.status == "completed":
                completed_chunks += 1
                if chunk_id not in batch.completed_chunk_ids:
                    batch.completed_chunk_ids.append(chunk_id)
            elif handled.checkpoint.status == "failed":
                failed_chunks += 1
                batch.last_error = handled.checkpoint.last_error
            else:
                skipped_chunks += 1

            manifest.updated_at = utcnow_iso()
            save_batch_manifest(manifest_path, manifest)
            _emit_progress(
                progress_callback=progress_callback,
                processed=processed_chunks,
                total=total_target_chunks,
                completed=completed_chunks,
                failed=failed_chunks,
                skipped=skipped_chunks,
                started_at=started_at,
            )

        if _batch_is_completed(batch, checkpoint):
            batch.status = "completed"
            batch.last_error = ""
        else:
            batch.status = "failed"
        batch.finished_at = utcnow_iso()
        manifest.updated_at = utcnow_iso()
        save_batch_manifest(manifest_path, manifest)

    elapsed_seconds = max(0.0, time.monotonic() - started_at)
    return BatchRunResult(
        manifest_path=manifest_path,
        checkpoint_path=checkpoint_path,
        selected_batch_ids=selected_batch_ids,
        total_target_chunks=total_target_chunks,
        processed_chunks=processed_chunks,
        completed_chunks=completed_chunks,
        failed_chunks=failed_chunks,
        skipped_chunks=skipped_chunks,
        elapsed_seconds=elapsed_seconds,
        translated_chunks_path=translated_chunks_path,
        codex_jobs_log_path=codex_jobs_log_path,
        codex_failures_log_path=codex_failures_log_path,
    )


def _handle_chunk(
    *,
    book_id: str,
    workspace_root: Path,
    batch_id: str,
    chunk_plan: ChunkPlan,
    translated_dir: Path,
    backend: Any,
    timeout_seconds: int,
    max_attempts: int,
    strict_json: bool,
) -> ChunkHandleResult:
    chunk = chunk_plan.chunk
    if chunk_plan.action in {"skip", "reuse_tm", "reuse_repeat", "reuse_cache"}:
        target_text = _resolve_local_target_text(chunk_plan)
        output_path = _write_chunk_output(
            translated_dir=translated_dir,
            chunk_id=chunk.chunk_id,
            payload={
                "chunk_id": chunk.chunk_id,
                "batch_id": batch_id,
                "status": "completed",
                "source": chunk_plan.action,
                "target_text": target_text,
                "job_id": "",
                "updated_at": utcnow_iso(),
            },
        )
        checkpoint = ChunkCheckpoint(
            chunk_id=chunk.chunk_id,
            batch_id=batch_id,
            status="completed",
            source=chunk_plan.action,
            attempts=1,
            output_path=str(output_path),
            target_text=target_text,
        )
        return ChunkHandleResult(
            checkpoint=checkpoint,
            translated_chunk_row={
                "chunk_id": chunk.chunk_id,
                "batch_id": batch_id,
                "source": checkpoint.source,
                "status": checkpoint.status,
                "target_text": checkpoint.target_text,
                "job_id": "",
                "output_path": checkpoint.output_path,
                "updated_at": checkpoint.updated_at,
            },
        )

    glossary = _build_glossary_subset(chunk_plan)
    style_guide = ""
    chapter_notes = ""
    style_hints: list[str] = []
    if chunk_plan.context_package is not None:
        style_hints = list(chunk_plan.context_package.style_rules)
        style_guide = "\n".join(style_hints)
        chapter_notes = chunk_plan.context_package.chapter_notes_excerpt

    translate_request = ChunkTranslationRequest(
        workspace_root=workspace_root,
        book_id=book_id,
        chunk=chunk,
        glossary=glossary,
        style_hints=style_hints,
        style_guide=style_guide,
        chapter_notes=chapter_notes,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        template_id=chunk_plan.template_id,
        job_id=f"{batch_id}-{_slugify(chunk.chunk_id)}",
    )
    translated = backend.translate_chunk(translate_request)

    codex_job_row = {
        "book_id": book_id,
        "batch_id": batch_id,
        "chunk_id": chunk.chunk_id,
        "job_id": translated.job.job_id,
        "success": translated.result.success,
        "return_code": translated.result.return_code,
        "attempt_count": translated.result.attempt_count,
        "output_path": translated.result.output_path or "",
        "failure_reason": translated.result.failure_reason or "",
        "backend": str(getattr(backend, "backend_name", "unknown")),
        "stage": "translation",
        "updated_at": utcnow_iso(),
    }

    if not translated.result.success or translated.output_payload is None:
        if not strict_json:
            best_effort = _best_effort_json_payload(translated.result.output_path)
            if best_effort is not None:
                text = _extract_best_effort_text(best_effort)
                if text:
                    output_path = _write_chunk_output(
                        translated_dir=translated_dir,
                        chunk_id=chunk.chunk_id,
                        payload={
                            "chunk_id": chunk.chunk_id,
                            "batch_id": batch_id,
                            "status": "completed",
                            "source": "codex_best_effort",
                            "target_text": text,
                            "job_id": translated.job.job_id,
                            "output_path": translated.result.output_path or "",
                            "updated_at": utcnow_iso(),
                        },
                    )
                    checkpoint = ChunkCheckpoint(
                        chunk_id=chunk.chunk_id,
                        batch_id=batch_id,
                        status="completed",
                        source="codex_best_effort",
                        attempts=max(1, translated.result.attempt_count),
                        job_id=translated.job.job_id,
                        output_path=str(output_path),
                        target_text=text,
                    )
                    codex_job_row["success"] = True
                    codex_job_row["failure_reason"] = ""
                    codex_job_row["best_effort"] = True
                    return ChunkHandleResult(
                        checkpoint=checkpoint,
                        translated_chunk_row={
                            "chunk_id": chunk.chunk_id,
                            "batch_id": batch_id,
                            "source": checkpoint.source,
                            "status": checkpoint.status,
                            "target_text": checkpoint.target_text,
                            "job_id": checkpoint.job_id,
                            "output_path": checkpoint.output_path,
                            "updated_at": checkpoint.updated_at,
                        },
                        codex_job_row=codex_job_row,
                    )

        checkpoint = ChunkCheckpoint(
            chunk_id=chunk.chunk_id,
            batch_id=batch_id,
            status="failed",
            source="codex",
            attempts=max(1, translated.result.attempt_count),
            job_id=translated.job.job_id,
            output_path=translated.result.output_path or "",
            last_error=translated.result.failure_reason or translated.result.stderr or "unknown_error",
        )
        return ChunkHandleResult(
            checkpoint=checkpoint,
            codex_job_row=codex_job_row,
            codex_failure_row={
                "book_id": book_id,
                "batch_id": batch_id,
                "chunk_id": chunk.chunk_id,
                "job_id": translated.job.job_id,
                "failure_reason": checkpoint.last_error,
                "attempt_count": checkpoint.attempts,
                "output_path": checkpoint.output_path,
                "updated_at": checkpoint.updated_at,
            },
        )

    target_text = str(translated.output_payload.get("translated_text", ""))
    output_path = _write_chunk_output(
        translated_dir=translated_dir,
        chunk_id=chunk.chunk_id,
        payload={
            "chunk_id": chunk.chunk_id,
            "batch_id": batch_id,
            "status": "completed",
            "source": "codex",
            "target_text": target_text,
            "job_id": translated.job.job_id,
            "output_path": translated.result.output_path or "",
            "updated_at": utcnow_iso(),
        },
    )
    checkpoint = ChunkCheckpoint(
        chunk_id=chunk.chunk_id,
        batch_id=batch_id,
        status="completed",
        source="codex",
        attempts=max(1, translated.result.attempt_count),
        job_id=translated.job.job_id,
        output_path=str(output_path),
        target_text=target_text,
    )
    return ChunkHandleResult(
        checkpoint=checkpoint,
        translated_chunk_row={
            "chunk_id": chunk.chunk_id,
            "batch_id": batch_id,
            "source": checkpoint.source,
            "status": checkpoint.status,
            "target_text": checkpoint.target_text,
            "job_id": checkpoint.job_id,
            "output_path": checkpoint.output_path,
            "updated_at": checkpoint.updated_at,
        },
        codex_job_row=codex_job_row,
    )


def _build_glossary_subset(chunk_plan: ChunkPlan) -> list[dict[str, str]]:
    if chunk_plan.context_package is None:
        return []
    terms: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in [*chunk_plan.context_package.exact_glossary, *chunk_plan.context_package.fuzzy_glossary]:
        source = item.source_term.strip()
        target = item.target_term.strip()
        if not source or not target:
            continue
        key = source.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append({"source": source, "target": target, "note": item.notes})
    for decision in chunk_plan.context_package.chapter_term_decisions:
        source = str(decision.get("source", "")).strip()
        target = str(decision.get("target", "")).strip()
        if not source or not target:
            continue
        key = source.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append({"source": source, "target": target, "note": str(decision.get("reason", ""))})
    return terms


def _resolve_local_target_text(plan: ChunkPlan) -> str:
    if plan.prefilter.target_text:
        return plan.prefilter.target_text
    if plan.cache_hit_output is not None and plan.cache_hit_output.exists():
        parsed = load_and_validate_output_json(
            plan.cache_hit_output,
            expected_job_id=None,
            expected_template_id="translate_chunk",
        )
        if parsed.payload is not None:
            return str(parsed.payload.get("translated_text", ""))
    if plan.action == "skip":
        return plan.chunk.source_text
    return ""


def _write_chunk_output(*, translated_dir: Path, chunk_id: str, payload: dict[str, Any]) -> Path:
    chunks_dir = translated_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    path = chunks_dir / f"{_slugify(chunk_id)}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _append_optional_jsonl(path: Path, payload: dict[str, Any] | None) -> None:
    if payload is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _best_effort_json_payload(output_path: str | None) -> dict[str, Any] | None:
    if not output_path:
        return None
    path = Path(output_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_best_effort_text(payload: dict[str, Any]) -> str:
    for key in ("translated_text", "target_text", "edited_text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _batch_is_completed(batch: BatchRecord, checkpoint: TranslationCheckpoint) -> bool:
    if not batch.chunk_ids:
        return True
    for chunk_id in batch.chunk_ids:
        chunk_state = checkpoint.chunks.get(chunk_id)
        if chunk_state is None or chunk_state.status != "completed":
            return False
    return True


def _count_target_chunks(batches: list[BatchRecord], checkpoint: TranslationCheckpoint) -> int:
    total = 0
    for batch in batches:
        for chunk_id in batch.chunk_ids:
            state = checkpoint.chunks.get(chunk_id)
            if state is not None and state.status == "completed":
                continue
            total += 1
    return total


def _emit_progress(
    *,
    progress_callback: ProgressCallback | None,
    processed: int,
    total: int,
    completed: int,
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

    message = (
        f"Progress {processed}/{total} | completed={completed} failed={failed} skipped={skipped} "
        f"| elapsed={_format_duration(elapsed)} eta={_format_duration(eta_seconds)}"
    )
    progress_callback(message)


def _format_duration(seconds: float) -> str:
    whole = int(max(0.0, seconds))
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _find_batch_index(batches: list[BatchRecord], batch_id: str) -> int:
    for idx, batch in enumerate(batches):
        if batch.batch_id == batch_id:
            return idx
    raise ValueError(f"Unknown batch id: {batch_id}")


def _slugify(value: str) -> str:
    text = "".join(ch if ch.isalnum() else "-" for ch in value.lower())
    compact = "-".join(part for part in text.split("-") if part)
    return compact or "batch"


def _coerce_batch_status(value: Any) -> BatchStatus:
    status = str(value).strip().lower()
    if status in {"pending", "running", "completed", "failed"}:
        return cast(BatchStatus, status)
    return "pending"


def _coerce_checkpoint_status(value: Any) -> CheckpointStatus:
    status = str(value).strip().lower()
    if status in {"pending", "completed", "failed", "skipped"}:
        return cast(CheckpointStatus, status)
    return "pending"
