"""File contract for Codex CLI translation jobs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.models import CodexJob

INPUT_SCHEMA_VERSION = "gpttranslator.codex.input.v1"
PROMPT_TEMPLATE_SCHEMA_VERSION = "gpttranslator.codex.prompt_template.v1"
OUTPUT_SCHEMA_VERSION = "gpttranslator.codex.output.v1"
META_SCHEMA_VERSION = "gpttranslator.codex.meta.v1"

INPUT_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "GPTtranslator Codex Job Input",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "job", "payload"],
    "properties": {
        "schema_version": {"type": "string", "const": INPUT_SCHEMA_VERSION},
        "job": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "book_id",
                "job_id",
                "created_at",
                "source_language",
                "target_language",
                "output_path",
            ],
            "properties": {
                "book_id": {"type": "string", "minLength": 1},
                "job_id": {"type": "string", "minLength": 1},
                "created_at": {"type": "string", "format": "date-time"},
                "source_language": {"type": "string", "minLength": 2},
                "target_language": {"type": "string", "minLength": 2},
                "output_path": {"type": "string", "minLength": 1},
            },
        },
        "payload": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "chunk_id",
                "source_text",
                "context_before",
                "context_after",
                "glossary",
                "style_hints",
            ],
            "properties": {
                "chunk_id": {"type": "string", "minLength": 1},
                "source_text": {"type": "string", "minLength": 1},
                "context_before": {"type": "string"},
                "context_after": {"type": "string"},
                "glossary": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["source", "target"],
                        "properties": {
                            "source": {"type": "string", "minLength": 1},
                            "target": {"type": "string", "minLength": 1},
                            "note": {"type": "string"},
                        },
                    },
                },
                "style_hints": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}

PROMPT_TEMPLATE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "GPTtranslator Codex Prompt Template Payload",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "template_id",
        "template_version",
        "job_id",
        "input_json_path",
        "output_json_path",
        "output_schema_version",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": PROMPT_TEMPLATE_SCHEMA_VERSION},
        "template_id": {"type": "string", "minLength": 1},
        "template_version": {"type": "integer", "minimum": 1},
        "job_id": {"type": "string", "minLength": 1},
        "input_json_path": {"type": "string", "minLength": 1},
        "output_json_path": {"type": "string", "minLength": 1},
        "output_schema_version": {"type": "string", "const": OUTPUT_SCHEMA_VERSION},
    },
}

OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "GPTtranslator Codex Job Output",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "job_id", "status", "translated_text", "notes", "errors"],
    "properties": {
        "schema_version": {"type": "string", "const": OUTPUT_SCHEMA_VERSION},
        "job_id": {"type": "string", "minLength": 1},
        "status": {"type": "string", "enum": ["ok", "failed"]},
        "translated_text": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
        "errors": {"type": "array", "items": {"type": "string"}},
    },
}

RECOVERY_POLICY: dict[str, dict[str, Any]] = {
    "invalid_json": {
        "retry": True,
        "description": "Output JSON is malformed and cannot be parsed.",
    },
    "partial_json": {
        "retry": True,
        "description": "Output JSON appears truncated or empty.",
    },
    "timeout": {
        "retry": True,
        "description": "Codex process exceeded timeout.",
    },
    "interrupted_process": {
        "retry": True,
        "description": "Codex process ended by signal or keyboard interruption.",
    },
    "missing_output_file": {
        "retry": True,
        "description": "Codex process exited without creating output.json.",
    },
    "output_schema_validation_failed": {
        "retry": True,
        "description": "output.json is valid JSON but does not satisfy strict output contract.",
    },
    "process_spawn_error": {
        "retry": False,
        "description": "Codex process could not start.",
    },
}


@dataclass(slots=True, frozen=True)
class CodexJobPaths:
    """Resolved file paths for one file-based Codex job."""

    job_dir: Path
    input_json: Path
    prompt_md: Path
    output_json: Path
    raw_stdout: Path
    raw_stderr: Path
    meta_json: Path


@dataclass(slots=True, frozen=True)
class OutputLoadResult:
    """Result of parsing and validating output.json."""

    payload: dict[str, Any] | None
    failure_reason: str | None = None
    error_message: str | None = None


def utcnow_iso() -> str:
    """Return timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


def build_codex_job_paths(workspace_root: Path, book_id: str, job_id: str) -> CodexJobPaths:
    """Resolve canonical job artifacts under workspace/<book_id>/jobs/<job_id>/."""

    job_dir = (workspace_root / book_id / "jobs" / job_id).resolve()
    return CodexJobPaths(
        job_dir=job_dir,
        input_json=job_dir / "input.json",
        prompt_md=job_dir / "prompt.md",
        output_json=job_dir / "output.json",
        raw_stdout=job_dir / "raw_stdout.txt",
        raw_stderr=job_dir / "raw_stderr.txt",
        meta_json=job_dir / "meta.json",
    )


def build_prompt_template_payload(job_id: str, input_json_path: Path, output_json_path: Path) -> dict[str, Any]:
    """Build structured prompt template payload for one job."""

    return {
        "schema_version": PROMPT_TEMPLATE_SCHEMA_VERSION,
        "template_id": "translate_chunk_v1",
        "template_version": 1,
        "job_id": job_id,
        "input_json_path": str(input_json_path),
        "output_json_path": str(output_json_path),
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
    }


def render_codex_prompt_markdown(template_payload: dict[str, Any]) -> str:
    """Render prompt.md that directs Codex to write only output.json."""

    errors = validate_prompt_template_payload(template_payload)
    if errors:
        message = "; ".join(errors)
        raise ValueError(f"Prompt template payload is invalid: {message}")

    output_skeleton = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "job_id": template_payload["job_id"],
        "status": "ok",
        "translated_text": "<translated text>",
        "notes": [],
        "errors": [],
    }

    schema_json = json.dumps(OUTPUT_JSON_SCHEMA, indent=2, ensure_ascii=False)
    skeleton_json = json.dumps(output_skeleton, indent=2, ensure_ascii=False)

    return (
        "# GPTtranslator Codex Job\n\n"
        f"- Prompt schema version: `{PROMPT_TEMPLATE_SCHEMA_VERSION}`\n"
        f"- Template id: `{template_payload['template_id']}`\n"
        f"- Template version: `{template_payload['template_version']}`\n"
        f"- Job id: `{template_payload['job_id']}`\n\n"
        "## Task\n\n"
        f"1. Read the input JSON file at `{template_payload['input_json_path']}`.\n"
        "2. Translate `payload.source_text` according to the provided glossary and style hints.\n"
        f"3. Write exactly one JSON object to `{template_payload['output_json_path']}`.\n"
        "4. Do not print translation result to stdout or stderr.\n"
        "5. The JSON in output.json must strictly match the schema below.\n\n"
        "## Required output schema\n\n"
        "```json\n"
        f"{schema_json}\n"
        "```\n\n"
        "## Required output object skeleton\n\n"
        "```json\n"
        f"{skeleton_json}\n"
        "```\n"
    )


def validate_prompt_template_payload(payload: dict[str, Any]) -> list[str]:
    """Validate prompt template payload shape."""

    errors: list[str] = []
    if payload.get("schema_version") != PROMPT_TEMPLATE_SCHEMA_VERSION:
        errors.append("schema_version must match prompt template contract")
    if not _is_non_empty_string(payload.get("template_id")):
        errors.append("template_id must be a non-empty string")
    if not isinstance(payload.get("template_version"), int) or int(payload["template_version"]) < 1:
        errors.append("template_version must be an integer >= 1")
    if not _is_non_empty_string(payload.get("job_id")):
        errors.append("job_id must be a non-empty string")
    if not _is_non_empty_string(payload.get("input_json_path")):
        errors.append("input_json_path must be a non-empty string")
    if not _is_non_empty_string(payload.get("output_json_path")):
        errors.append("output_json_path must be a non-empty string")
    if payload.get("output_schema_version") != OUTPUT_SCHEMA_VERSION:
        errors.append("output_schema_version must match output schema contract")
    return errors


def validate_input_payload(payload: Any) -> list[str]:
    """Validate input.json against strict contract checks."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["input payload root must be an object"]

    expected_keys = {"schema_version", "job", "payload"}
    errors.extend(_validate_object_keys(payload, expected_keys, "input"))

    if payload.get("schema_version") != INPUT_SCHEMA_VERSION:
        errors.append("input.schema_version must match input schema contract")

    job = payload.get("job")
    if not isinstance(job, dict):
        errors.append("input.job must be an object")
    else:
        job_keys = {
            "book_id",
            "job_id",
            "created_at",
            "source_language",
            "target_language",
            "output_path",
        }
        errors.extend(_validate_object_keys(job, job_keys, "input.job"))

        for key in ("book_id", "job_id", "created_at", "source_language", "target_language", "output_path"):
            if not _is_non_empty_string(job.get(key)):
                errors.append(f"input.job.{key} must be a non-empty string")

    content = payload.get("payload")
    if not isinstance(content, dict):
        errors.append("input.payload must be an object")
        return errors

    payload_keys = {
        "chunk_id",
        "source_text",
        "context_before",
        "context_after",
        "glossary",
        "style_hints",
    }
    errors.extend(_validate_object_keys(content, payload_keys, "input.payload"))

    for key in ("chunk_id", "source_text", "context_before", "context_after"):
        value = content.get(key)
        if not isinstance(value, str):
            errors.append(f"input.payload.{key} must be a string")
    if isinstance(content.get("source_text"), str) and not content["source_text"].strip():
        errors.append("input.payload.source_text must not be empty")

    glossary = content.get("glossary")
    if not isinstance(glossary, list):
        errors.append("input.payload.glossary must be an array")
    else:
        for index, term in enumerate(glossary):
            if not isinstance(term, dict):
                errors.append(f"input.payload.glossary[{index}] must be an object")
                continue

            term_path = f"input.payload.glossary[{index}]"
            term_keys = set(term.keys())
            extra = term_keys - {"source", "target", "note"}
            if extra:
                extra_list = ", ".join(sorted(extra))
                errors.append(f"{term_path} has unexpected fields: {extra_list}")
            for key in ("source", "target"):
                if not _is_non_empty_string(term.get(key)):
                    errors.append(f"{term_path}.{key} must be a non-empty string")
            note = term.get("note")
            if note is not None and not isinstance(note, str):
                errors.append(f"{term_path}.note must be a string when present")

    style_hints = content.get("style_hints")
    if not isinstance(style_hints, list):
        errors.append("input.payload.style_hints must be an array")
    else:
        for index, hint in enumerate(style_hints):
            if not isinstance(hint, str):
                errors.append(f"input.payload.style_hints[{index}] must be a string")

    return errors


def validate_output_payload(payload: Any, expected_job_id: str | None = None) -> list[str]:
    """Strictly validate output payload contract."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["output payload root must be an object"]

    expected_keys = {"schema_version", "job_id", "status", "translated_text", "notes", "errors"}
    errors.extend(_validate_object_keys(payload, expected_keys, "output"))

    if payload.get("schema_version") != OUTPUT_SCHEMA_VERSION:
        errors.append("output.schema_version must match output schema contract")

    job_id = payload.get("job_id")
    if not _is_non_empty_string(job_id):
        errors.append("output.job_id must be a non-empty string")
    if expected_job_id is not None and job_id != expected_job_id:
        errors.append("output.job_id does not match expected job id")

    status = payload.get("status")
    if status not in {"ok", "failed"}:
        errors.append("output.status must be either 'ok' or 'failed'")

    translated_text = payload.get("translated_text")
    if not isinstance(translated_text, str):
        errors.append("output.translated_text must be a string")
    elif status == "ok" and not translated_text.strip():
        errors.append("output.translated_text must be non-empty when status is 'ok'")

    notes = payload.get("notes")
    if not isinstance(notes, list):
        errors.append("output.notes must be an array")
    else:
        for index, note in enumerate(notes):
            if not isinstance(note, str):
                errors.append(f"output.notes[{index}] must be a string")

    output_errors = payload.get("errors")
    if not isinstance(output_errors, list):
        errors.append("output.errors must be an array")
    else:
        for index, message in enumerate(output_errors):
            if not isinstance(message, str):
                errors.append(f"output.errors[{index}] must be a string")

    if status == "failed" and isinstance(output_errors, list) and len(output_errors) == 0:
        errors.append("output.errors must contain at least one message when status is 'failed'")

    return errors


def load_and_validate_output_json(output_json_path: Path, expected_job_id: str) -> OutputLoadResult:
    """Load output.json and return normalized parse/validation result."""

    if not output_json_path.exists():
        return OutputLoadResult(
            payload=None,
            failure_reason="missing_output_file",
            error_message=f"output.json was not created: {output_json_path}",
        )

    raw_text = output_json_path.read_text(encoding="utf-8")
    if not raw_text.strip():
        return OutputLoadResult(
            payload=None,
            failure_reason="partial_json",
            error_message="output.json is empty",
        )

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        failure_reason = classify_json_failure(raw_text, exc)
        return OutputLoadResult(
            payload=None,
            failure_reason=failure_reason,
            error_message=f"output.json parse error: {exc.msg} at line {exc.lineno} column {exc.colno}",
        )

    validation_errors = validate_output_payload(payload, expected_job_id=expected_job_id)
    if validation_errors:
        return OutputLoadResult(
            payload=None,
            failure_reason="output_schema_validation_failed",
            error_message="; ".join(validation_errors),
        )

    return OutputLoadResult(payload=payload)


def classify_json_failure(raw_text: str, exc: json.JSONDecodeError) -> str:
    """Classify malformed JSON as invalid or partial for recovery policy."""

    message = exc.msg.lower()
    stripped = raw_text.rstrip()

    if not stripped:
        return "partial_json"
    if "unterminated" in message:
        return "partial_json"
    if stripped.startswith("{") and not stripped.endswith("}"):
        return "partial_json"
    if exc.pos >= max(len(raw_text) - 2, 0):
        return "partial_json"
    return "invalid_json"


def is_retryable_failure(failure_reason: str) -> bool:
    """Return whether a recovery failure reason is configured as retryable."""

    policy = RECOVERY_POLICY.get(failure_reason)
    if policy is None:
        return False
    return bool(policy.get("retry", False))


def create_codex_job(
    workspace_root: Path,
    book_id: str,
    job_id: str,
    chunk_id: str,
    source_text: str,
    source_language: str = "en",
    target_language: str = "ru",
    context_before: str = "",
    context_after: str = "",
    glossary: list[dict[str, str]] | None = None,
    style_hints: list[str] | None = None,
    timeout_seconds: int = 120,
    max_attempts: int = 3,
) -> CodexJob:
    """Create canonical job files and return a CodexJob descriptor."""

    if not _is_non_empty_string(book_id):
        raise ValueError("book_id must be a non-empty string")
    if not _is_non_empty_string(job_id):
        raise ValueError("job_id must be a non-empty string")
    if not _is_non_empty_string(chunk_id):
        raise ValueError("chunk_id must be a non-empty string")
    if not isinstance(source_text, str) or not source_text.strip():
        raise ValueError("source_text must be a non-empty string")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be >= 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    paths = build_codex_job_paths(workspace_root, book_id, job_id)
    paths.job_dir.mkdir(parents=True, exist_ok=True)

    input_payload = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "job": {
            "book_id": book_id,
            "job_id": job_id,
            "created_at": utcnow_iso(),
            "source_language": source_language,
            "target_language": target_language,
            "output_path": str(paths.output_json),
        },
        "payload": {
            "chunk_id": chunk_id,
            "source_text": source_text,
            "context_before": context_before,
            "context_after": context_after,
            "glossary": _normalize_glossary(glossary or []),
            "style_hints": [str(item) for item in (style_hints or [])],
        },
    }

    input_errors = validate_input_payload(input_payload)
    if input_errors:
        raise ValueError(f"input payload is invalid: {'; '.join(input_errors)}")

    prompt_template_payload = build_prompt_template_payload(
        job_id=job_id,
        input_json_path=paths.input_json,
        output_json_path=paths.output_json,
    )
    prompt_text = render_codex_prompt_markdown(prompt_template_payload)

    meta_payload = build_initial_meta_payload(
        book_id=book_id,
        job_id=job_id,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )

    write_json_file(paths.input_json, input_payload)
    paths.prompt_md.write_text(prompt_text, encoding="utf-8")
    paths.output_json.write_text("", encoding="utf-8")
    paths.raw_stdout.write_text("", encoding="utf-8")
    paths.raw_stderr.write_text("", encoding="utf-8")
    write_json_file(paths.meta_json, meta_payload)

    return CodexJob(
        job_id=job_id,
        prompt_path=str(paths.prompt_md),
        input_path=str(paths.input_json),
        output_path=str(paths.output_json),
        raw_stdout_path=str(paths.raw_stdout),
        raw_stderr_path=str(paths.raw_stderr),
        meta_path=str(paths.meta_json),
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        status="queued",
    )


def build_initial_meta_payload(
    book_id: str,
    job_id: str,
    timeout_seconds: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Build initial meta.json payload for job orchestration."""

    timestamp = utcnow_iso()
    return {
        "schema_version": META_SCHEMA_VERSION,
        "book_id": book_id,
        "job_id": job_id,
        "status": "queued",
        "created_at": timestamp,
        "updated_at": timestamp,
        "timeout_seconds": timeout_seconds,
        "max_attempts": max_attempts,
        "attempts": [],
        "paths": {
            "input_json": "input.json",
            "prompt_md": "prompt.md",
            "output_json": "output.json",
            "raw_stdout": "raw_stdout.txt",
            "raw_stderr": "raw_stderr.txt",
            "meta_json": "meta.json",
        },
    }


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    """Persist JSON with stable formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize_glossary(glossary: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for term in glossary:
        source = str(term.get("source", "")).strip()
        target = str(term.get("target", "")).strip()
        if not source or not target:
            continue
        entry: dict[str, str] = {"source": source, "target": target}
        note = term.get("note")
        if note is not None:
            entry["note"] = str(note)
        normalized.append(entry)
    return normalized


def _validate_object_keys(payload: dict[str, Any], expected_keys: set[str], path: str) -> list[str]:
    errors: list[str] = []
    actual_keys = set(payload.keys())
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys

    if missing:
        missing_list = ", ".join(sorted(missing))
        errors.append(f"{path} is missing required fields: {missing_list}")
    if extra:
        extra_list = ", ".join(sorted(extra))
        errors.append(f"{path} has unexpected fields: {extra_list}")
    return errors


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
