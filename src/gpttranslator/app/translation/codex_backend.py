"""High-level Codex translation backend orchestration."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Sequence, cast

from ..core.logging import get_logger
from ..core.models import Chunk, CodexJob, CodexResult
from .backends.base import BaseTranslationBackend
from .backends.codex_cli import CodexCliBackend as _ProtocolCodexCliBackend
from .protocol import (
    OUTPUT_SCHEMA_VERSION,
    create_codex_job,
    load_and_validate_output_json,
    utcnow_iso,
    write_json_file,
)

CommandBuilder = Callable[[CodexJob], Sequence[str]]
BackendName = Literal["codex-cli", "mock"]


class BackendUnavailableError(RuntimeError):
    """Raised when requested translation backend is not available."""


@dataclass(frozen=True, slots=True)
class ChunkTranslationRequest:
    """Input data needed to run one chunk through Codex backend."""

    workspace_root: Path
    book_id: str
    chunk: Chunk
    glossary: list[dict[str, str]] | None = None
    style_hints: list[str] | None = None
    style_guide: str = ""
    chapter_notes: str = ""
    translated_text: str = ""
    strict_terminology: bool = True
    preserve_literalness: bool = False
    editorial_rewrite_level: Literal["light", "medium", "aggressive"] = "medium"
    source_language: str = "en"
    target_language: str = "ru"
    template_id: str = "translate_chunk"
    timeout_seconds: int = 120
    max_attempts: int = 3
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkTranslationResult:
    """Normalized result for one chunk translation backend call."""

    job: CodexJob
    result: CodexResult
    output_payload: dict[str, Any] | None


class CodexCliBackend(_ProtocolCodexCliBackend):
    """Production backend that uses external `codex` CLI with file exchange."""

    backend_name = "codex-cli"

    def __init__(
        self,
        codex_command: str = "codex",
        timeout_seconds: int = 120,
        max_attempts: int = 3,
        dry_run: bool = False,
        command_builder: CommandBuilder | None = None,
    ) -> None:
        super().__init__(
            codex_command=codex_command,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            command_builder=command_builder,
        )
        self.dry_run = dry_run
        self.logger = get_logger("translation.codex_backend")

    def ensure_available(self) -> None:
        """Validate Codex CLI availability and raise a clear error when missing."""

        if self.command_builder is not None:
            return
        if shutil.which(self.codex_command) is None:
            raise BackendUnavailableError(
                f"Codex CLI executable '{self.codex_command}' is not available in PATH. "
                "Install Codex CLI and ensure it is accessible from the current shell."
            )

    def run_job(self, job: CodexJob) -> CodexResult:
        """Run low-level job or emulate success in dry-run mode."""

        if self.dry_run:
            self.logger.info("codex dry-run job prepared: %s", job.job_id)
            return self._run_dry_job(job)

        self.ensure_available()
        self.logger.info("starting codex job via subprocess: %s", job.job_id)
        return super().run_job(job)

    def prepare_chunk_job(self, request: ChunkTranslationRequest) -> CodexJob:
        """Create file-based job artifacts (input/prompt/output/log/meta files)."""

        job_id = request.job_id or self._build_job_id(request.chunk.chunk_id)
        job = _create_job_from_request(request=request, job_id=job_id)
        self.logger.info("chunk job created: chunk_id=%s job_id=%s", request.chunk.chunk_id, job_id)
        return job

    def translate_chunk(self, request: ChunkTranslationRequest) -> ChunkTranslationResult:
        """Prepare job, execute backend call, and return validated payload."""

        job = self.prepare_chunk_job(request)
        result = self.run_job(job)

        payload: dict[str, Any] | None = None
        if result.success:
            output_result = load_and_validate_output_json(
                Path(job.output_path),
                expected_job_id=job.job_id,
                expected_template_id=request.template_id,
            )
            if output_result.payload is None:
                result = CodexResult(
                    job_id=job.job_id,
                    return_code=result.return_code,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    success=False,
                    output_path=result.output_path,
                    failure_reason=output_result.failure_reason,
                    meta_path=result.meta_path,
                    attempt_count=result.attempt_count,
                )
            else:
                payload = output_result.payload

        if result.success:
            self.logger.info("codex chunk translation succeeded: job_id=%s", job.job_id)
        else:
            self.logger.warning(
                "codex chunk translation failed: job_id=%s reason=%s",
                job.job_id,
                result.failure_reason,
            )

        return ChunkTranslationResult(job=job, result=result, output_payload=payload)

    def _run_dry_job(self, job: CodexJob) -> CodexResult:
        paths = self._normalize_job_paths(job)
        input_payload = _load_input_payload(paths.input_json)
        job_payload = input_payload.get("job", {}) if isinstance(input_payload, dict) else {}
        payload_root = input_payload.get("payload", {}) if isinstance(input_payload, dict) else {}
        template_id = "translate_chunk"
        if isinstance(job_payload, dict):
            raw_template_id = job_payload.get("template_id")
            if isinstance(raw_template_id, str) and raw_template_id.strip():
                template_id = raw_template_id
        if not isinstance(payload_root, dict):
            payload_root = {}
        chunk_id = str(payload_root.get("chunk_id", "dry-run-chunk"))
        chapter_id = str(payload_root.get("chapter_id", ""))
        chunk_ids = [str(item) for item in payload_root.get("chunk_ids", []) if isinstance(item, str)]
        block_ids = [str(item) for item in payload_root.get("block_ids", []) if isinstance(item, str)]
        markers = [str(item) for item in payload_root.get("footnote_markers", []) if isinstance(item, str)]
        placeholder_payload: dict[str, Any] = {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "template_id": template_id,
            "job_id": job.job_id,
            "status": "ok",
            "notes": ["dry_run: codex subprocess was not invoked"],
            "errors": [],
        }
        if template_id == "editorial_pass":
            placeholder_payload.update(
                {
                    "chunk_id": chunk_id,
                    "block_ids": block_ids,
                    "edited_text": "[dry-run] editorial placeholder",
                    "preserved_footnote_markers": markers,
                    "editorial_actions": [],
                }
            )
        elif template_id == "chapter_summary":
            placeholder_payload.update(
                {
                    "chapter_id": chapter_id or "chapter-dry",
                    "chunk_ids": chunk_ids or [chunk_id],
                    "block_ids": block_ids,
                    "summary_markdown": "",
                    "key_points": [],
                    "preserved_footnote_markers": markers,
                }
            )
        elif template_id == "glossary_update_proposal":
            placeholder_payload.update(
                {
                    "chapter_id": chapter_id or "chapter-dry",
                    "chunk_ids": chunk_ids or [chunk_id],
                    "block_ids": block_ids,
                    "preserved_footnote_markers": markers,
                    "proposals": [],
                }
            )
        elif template_id == "terminology_check":
            placeholder_payload.update(
                {
                    "chunk_id": chunk_id,
                    "block_ids": block_ids,
                    "preserved_footnote_markers": markers,
                    "terminology_passed": True,
                    "violations": [],
                }
            )
        elif template_id == "semantic_qa":
            placeholder_payload.update(
                {
                    "chunk_id": chunk_id,
                    "block_ids": block_ids,
                    "preserved_footnote_markers": markers,
                    "qa_passed": True,
                    "issues": [],
                }
            )
        else:
            placeholder_payload.update(
                {
                    "chunk_id": chunk_id,
                    "block_ids": block_ids,
                    "translated_text": "[dry-run] translation placeholder",
                    "preserved_footnote_markers": markers,
                }
            )
        write_json_file(paths.output_json, placeholder_payload)

        timestamp = utcnow_iso()
        meta_payload = {
            "schema_version": "gpttranslator.codex.meta.v1",
            "book_id": self._book_id_from_job_dir(paths.job_dir),
            "job_id": job.job_id,
            "status": "dry_run",
            "created_at": timestamp,
            "updated_at": timestamp,
            "timeout_seconds": int(job.timeout_seconds or self.timeout_seconds),
            "max_attempts": int(job.max_attempts or self.max_attempts),
            "attempts": [
                {
                    "attempt": 0,
                    "started_at": timestamp,
                    "finished_at": timestamp,
                    "command": list(self._build_command(job)),
                    "return_code": 0,
                    "outcome": "dry_run",
                    "message": "Codex call skipped by dry-run mode.",
                    "retry_scheduled": False,
                }
            ],
            "paths": {
                "input_json": "input.json",
                "prompt_md": "prompt.md",
                "output_json": "output.json",
                "raw_stdout": "raw_stdout.txt",
                "raw_stderr": "raw_stderr.txt",
                "meta_json": "meta.json",
            },
        }
        write_json_file(paths.meta_json, meta_payload)
        paths.raw_stdout.write_text("dry_run: codex subprocess was not invoked\n", encoding="utf-8")
        paths.raw_stderr.write_text("", encoding="utf-8")

        return CodexResult(
            job_id=job.job_id,
            return_code=0,
            stdout="dry_run: codex subprocess was not invoked",
            stderr="",
            success=True,
            output_path=str(paths.output_json),
            meta_path=str(paths.meta_json),
            attempt_count=0,
        )

    def _build_job_id(self, chunk_id: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", chunk_id).strip("-")
        if not normalized:
            normalized = "chunk"
        timestamp = utcnow_iso().replace(":", "").replace("-", "")
        return f"job-{normalized}-{timestamp}"


class MockCodexBackend(BaseTranslationBackend):
    """Deterministic mock backend for tests without Codex subprocess."""

    backend_name = "mock"

    def __init__(self, fail: bool = False, fail_on_chunk_ids: set[str] | None = None) -> None:
        self.fail = fail
        self.fail_on_chunk_ids = set(fail_on_chunk_ids or set())

    def healthcheck(self) -> bool:
        return True

    def run_job(self, job: CodexJob) -> CodexResult:
        output_path = Path(job.output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        input_payload = _load_input_payload(Path(job.input_path))
        chunk_payload = input_payload.get("payload", {}) if isinstance(input_payload, dict) else {}
        job_payload = input_payload.get("job", {}) if isinstance(input_payload, dict) else {}
        if not isinstance(chunk_payload, dict):
            chunk_payload = {}
        if not isinstance(job_payload, dict):
            job_payload = {}

        chunk_id = str(chunk_payload.get("chunk_id", "unknown-chunk"))
        chapter_id = str(chunk_payload.get("chapter_id", ""))
        chunk_ids = [str(item) for item in chunk_payload.get("chunk_ids", []) if isinstance(item, str)]
        template_id = str(job_payload.get("template_id", "translate_chunk"))
        source_text = str(chunk_payload.get("source_text", ""))
        translated_text = str(chunk_payload.get("translated_text", ""))
        block_ids = [str(item) for item in chunk_payload.get("block_ids", []) if isinstance(item, str)]
        markers = [str(item) for item in chunk_payload.get("footnote_markers", []) if isinstance(item, str)]

        if self.fail or chunk_id in self.fail_on_chunk_ids:
            return CodexResult(
                job_id=job.job_id,
                return_code=1,
                stdout="",
                stderr="mock backend forced failure",
                success=False,
                output_path=str(output_path),
                failure_reason="mock_failure",
                meta_path=job.meta_path or None,
                attempt_count=1,
            )

        payload: dict[str, Any] = {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "template_id": template_id,
            "job_id": job.job_id,
            "status": "ok",
            "notes": ["mock_backend"],
            "errors": [],
        }
        if template_id == "editorial_pass":
            payload.update(
                {
                    "chunk_id": chunk_id,
                    "block_ids": block_ids,
                    "edited_text": f"[MOCK_EDIT] {translated_text or source_text}",
                    "preserved_footnote_markers": markers,
                    "editorial_actions": [
                        {
                            "action": "style_tightening",
                            "reason": "mock editorial pass applied",
                        }
                    ],
                }
            )
        elif template_id == "terminology_check":
            payload.update(
                {
                    "chunk_id": chunk_id,
                    "block_ids": block_ids,
                    "preserved_footnote_markers": markers,
                    "terminology_passed": True,
                    "violations": [],
                }
            )
        elif template_id == "semantic_qa":
            payload.update(
                {
                    "chunk_id": chunk_id,
                    "block_ids": block_ids,
                    "preserved_footnote_markers": markers,
                    "qa_passed": True,
                    "issues": [],
                }
            )
        elif template_id == "chapter_summary":
            payload.update(
                {
                    "chapter_id": chapter_id or "chapter-mock",
                    "chunk_ids": chunk_ids or [chunk_id],
                    "block_ids": block_ids,
                    "summary_markdown": f"Summary for {chapter_id or chunk_id}",
                    "key_points": [],
                    "preserved_footnote_markers": markers,
                }
            )
        elif template_id == "glossary_update_proposal":
            payload.update(
                {
                    "chapter_id": chapter_id or "chapter-mock",
                    "chunk_ids": chunk_ids or [chunk_id],
                    "block_ids": block_ids,
                    "preserved_footnote_markers": markers,
                    "proposals": [],
                }
            )
        else:
            payload.update(
                {
                    "chunk_id": chunk_id,
                    "block_ids": block_ids,
                    "translated_text": f"[MOCK_RU] {source_text}",
                    "preserved_footnote_markers": markers,
                }
            )
        write_json_file(output_path, payload)

        return CodexResult(
            job_id=job.job_id,
            return_code=0,
            stdout="mock backend translation completed",
            stderr="",
            success=True,
            output_path=str(output_path),
            meta_path=job.meta_path or None,
            attempt_count=1,
        )

    def prepare_chunk_job(self, request: ChunkTranslationRequest) -> CodexJob:
        """Create codex protocol files for mock execution."""

        job_id = request.job_id or f"mock-{re.sub(r'[^A-Za-z0-9._-]+', '-', request.chunk.chunk_id).strip('-')}"
        return _create_job_from_request(request=request, job_id=job_id)

    def translate_chunk(self, request: ChunkTranslationRequest) -> ChunkTranslationResult:
        """Mock chunk translation with structured output validation."""

        job = self.prepare_chunk_job(request)
        result = self.run_job(job)
        payload: dict[str, Any] | None = None
        if result.success:
            output_result = load_and_validate_output_json(
                Path(job.output_path),
                expected_job_id=job.job_id,
                expected_template_id=request.template_id,
            )
            if output_result.payload is None:
                result = CodexResult(
                    job_id=job.job_id,
                    return_code=result.return_code,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    success=False,
                    output_path=result.output_path,
                    failure_reason=output_result.failure_reason,
                    meta_path=result.meta_path,
                    attempt_count=result.attempt_count,
                )
            else:
                payload = output_result.payload

        return ChunkTranslationResult(job=job, result=result, output_payload=payload)


def build_translation_backend(
    *,
    backend: BackendName,
    codex_command: str = "codex",
    timeout_seconds: int = 120,
    max_attempts: int = 3,
    dry_run: bool = False,
    command_builder: CommandBuilder | None = None,
) -> BaseTranslationBackend:
    """Build translation backend implementation by CLI name."""

    if backend == "codex-cli":
        return CodexCliBackend(
            codex_command=codex_command,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            dry_run=dry_run,
            command_builder=command_builder,
        )
    if backend == "mock":
        return MockCodexBackend()
    raise ValueError(f"Unsupported backend: {backend}")


def parse_backend_name(raw_value: str) -> BackendName:
    """Parse CLI backend option and validate supported values."""

    value = raw_value.strip().lower()
    if value not in {"codex-cli", "mock"}:
        raise ValueError("backend must be one of: codex-cli, mock")
    return cast(BackendName, value)


def _extract_footnote_markers(footnote_refs: list[dict[str, Any]]) -> list[str]:
    markers: list[str] = []
    seen: set[str] = set()
    for item in footnote_refs:
        if not isinstance(item, dict):
            continue
        marker_raw = item.get("marker")
        if marker_raw is None:
            marker_raw = item.get("id")
        if marker_raw is None:
            continue
        marker = str(marker_raw).strip()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        markers.append(marker)
    return markers


def _load_input_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _create_job_from_request(*, request: ChunkTranslationRequest, job_id: str) -> CodexJob:
    return create_codex_job(
        workspace_root=request.workspace_root,
        book_id=request.book_id,
        job_id=job_id,
        chunk_id=request.chunk.chunk_id,
        source_text=request.chunk.source_text,
        translated_text=request.translated_text,
        source_language=request.source_language,
        target_language=request.target_language,
        context_before=request.chunk.local_context_before,
        context_after=request.chunk.local_context_after,
        glossary=request.glossary or [],
        style_hints=request.style_hints or list(request.chunk.glossary_hints),
        block_ids=list(request.chunk.block_ids),
        footnote_markers=_extract_footnote_markers(request.chunk.footnote_refs),
        style_guide=request.style_guide,
        chapter_notes=request.chapter_notes,
        strict_terminology=request.strict_terminology,
        preserve_literalness=request.preserve_literalness,
        editorial_rewrite_level=request.editorial_rewrite_level,
        chapter_id=request.chunk.chapter_id or "",
        chunk_ids=[request.chunk.chunk_id],
        template_id=request.template_id,
        timeout_seconds=max(1, request.timeout_seconds),
        max_attempts=max(1, request.max_attempts),
    )
