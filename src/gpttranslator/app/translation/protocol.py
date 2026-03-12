"""File contract and prompt templates for Codex CLI translation jobs."""

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


@dataclass(slots=True, frozen=True)
class PromptTemplateSpec:
    """Prompt template metadata and output contract."""

    template_id: str
    filename: str
    template_version: int
    output_schema: dict[str, Any]


def _string_schema(min_length: int = 0) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if min_length > 0:
        schema["minLength"] = min_length
    return schema


def _string_array_schema() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _common_output_schema(template_id: str, title: str, extra_properties: dict[str, Any], extra_required: list[str]) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "schema_version": {"type": "string", "const": OUTPUT_SCHEMA_VERSION},
        "template_id": {"type": "string", "const": template_id},
        "job_id": _string_schema(min_length=1),
        "status": {"type": "string", "enum": ["ok", "failed"]},
        "notes": _string_array_schema(),
        "errors": _string_array_schema(),
    }
    properties.update(extra_properties)

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "template_id", "job_id", "status", "notes", "errors", *extra_required],
        "properties": properties,
    }


PROMPT_OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "translate_chunk": _common_output_schema(
        template_id="translate_chunk",
        title="GPTtranslator Translate Chunk Output",
        extra_properties={
            "chunk_id": _string_schema(min_length=1),
            "block_ids": _string_array_schema(),
            "translated_text": _string_schema(),
            "preserved_footnote_markers": _string_array_schema(),
        },
        extra_required=["chunk_id", "block_ids", "translated_text", "preserved_footnote_markers"],
    ),
    "editorial_pass": _common_output_schema(
        template_id="editorial_pass",
        title="GPTtranslator Editorial Pass Output",
        extra_properties={
            "chunk_id": _string_schema(min_length=1),
            "block_ids": _string_array_schema(),
            "edited_text": _string_schema(),
            "preserved_footnote_markers": _string_array_schema(),
            "editorial_actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["action", "reason"],
                    "properties": {
                        "action": _string_schema(min_length=1),
                        "reason": _string_schema(min_length=1),
                    },
                },
            },
        },
        extra_required=["chunk_id", "block_ids", "edited_text", "preserved_footnote_markers", "editorial_actions"],
    ),
    "terminology_check": _common_output_schema(
        template_id="terminology_check",
        title="GPTtranslator Terminology Check Output",
        extra_properties={
            "chunk_id": _string_schema(min_length=1),
            "block_ids": _string_array_schema(),
            "preserved_footnote_markers": _string_array_schema(),
            "terminology_passed": {"type": "boolean"},
            "violations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_term", "expected_target", "severity", "message"],
                    "properties": {
                        "source_term": _string_schema(min_length=1),
                        "expected_target": _string_schema(min_length=1),
                        "found_text": _string_schema(),
                        "block_id": _string_schema(),
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "message": _string_schema(min_length=1),
                    },
                },
            },
        },
        extra_required=["chunk_id", "block_ids", "preserved_footnote_markers", "terminology_passed", "violations"],
    ),
    "semantic_qa": _common_output_schema(
        template_id="semantic_qa",
        title="GPTtranslator Semantic QA Output",
        extra_properties={
            "chunk_id": _string_schema(min_length=1),
            "block_ids": _string_array_schema(),
            "preserved_footnote_markers": _string_array_schema(),
            "qa_passed": {"type": "boolean"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["issue_id", "severity", "message"],
                    "properties": {
                        "issue_id": _string_schema(min_length=1),
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "message": _string_schema(min_length=1),
                        "block_id": _string_schema(),
                        "evidence": _string_schema(),
                    },
                },
            },
        },
        extra_required=["chunk_id", "block_ids", "preserved_footnote_markers", "qa_passed", "issues"],
    ),
    "chapter_summary": _common_output_schema(
        template_id="chapter_summary",
        title="GPTtranslator Chapter Summary Output",
        extra_properties={
            "chapter_id": _string_schema(min_length=1),
            "chunk_ids": _string_array_schema(),
            "block_ids": _string_array_schema(),
            "summary_markdown": _string_schema(),
            "key_points": _string_array_schema(),
            "preserved_footnote_markers": _string_array_schema(),
        },
        extra_required=["chapter_id", "chunk_ids", "block_ids", "summary_markdown", "key_points", "preserved_footnote_markers"],
    ),
    "glossary_update_proposal": _common_output_schema(
        template_id="glossary_update_proposal",
        title="GPTtranslator Glossary Update Proposal Output",
        extra_properties={
            "chapter_id": _string_schema(min_length=1),
            "chunk_ids": _string_array_schema(),
            "block_ids": _string_array_schema(),
            "preserved_footnote_markers": _string_array_schema(),
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_term", "suggested_target", "rationale", "evidence_chunk_ids"],
                    "properties": {
                        "source_term": _string_schema(min_length=1),
                        "suggested_target": _string_schema(min_length=1),
                        "rationale": _string_schema(min_length=1),
                        "evidence_chunk_ids": _string_array_schema(),
                    },
                },
            },
        },
        extra_required=["chapter_id", "chunk_ids", "block_ids", "preserved_footnote_markers", "proposals"],
    ),
}

PROMPT_TEMPLATE_SPECS: dict[str, PromptTemplateSpec] = {
    "translate_chunk": PromptTemplateSpec(
        template_id="translate_chunk",
        filename="translate_chunk.prompt.md",
        template_version=1,
        output_schema=PROMPT_OUTPUT_SCHEMAS["translate_chunk"],
    ),
    "editorial_pass": PromptTemplateSpec(
        template_id="editorial_pass",
        filename="editorial_pass.prompt.md",
        template_version=1,
        output_schema=PROMPT_OUTPUT_SCHEMAS["editorial_pass"],
    ),
    "terminology_check": PromptTemplateSpec(
        template_id="terminology_check",
        filename="terminology_check.prompt.md",
        template_version=1,
        output_schema=PROMPT_OUTPUT_SCHEMAS["terminology_check"],
    ),
    "semantic_qa": PromptTemplateSpec(
        template_id="semantic_qa",
        filename="semantic_qa.prompt.md",
        template_version=1,
        output_schema=PROMPT_OUTPUT_SCHEMAS["semantic_qa"],
    ),
    "chapter_summary": PromptTemplateSpec(
        template_id="chapter_summary",
        filename="chapter_summary.prompt.md",
        template_version=1,
        output_schema=PROMPT_OUTPUT_SCHEMAS["chapter_summary"],
    ),
    "glossary_update_proposal": PromptTemplateSpec(
        template_id="glossary_update_proposal",
        filename="glossary_update_proposal.prompt.md",
        template_version=1,
        output_schema=PROMPT_OUTPUT_SCHEMAS["glossary_update_proposal"],
    ),
}

OUTPUT_JSON_SCHEMA = PROMPT_OUTPUT_SCHEMAS["translate_chunk"]

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
                "template_id",
                "created_at",
                "source_language",
                "target_language",
                "output_path",
            ],
            "properties": {
                "book_id": _string_schema(min_length=1),
                "job_id": _string_schema(min_length=1),
                "template_id": _string_schema(min_length=1),
                "created_at": _string_schema(min_length=1),
                "source_language": _string_schema(min_length=2),
                "target_language": _string_schema(min_length=2),
                "output_path": _string_schema(min_length=1),
            },
        },
        "payload": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "chunk_id",
                "block_ids",
                "source_text",
                "context_before",
                "context_after",
                "footnote_markers",
                "glossary",
                "style_hints",
                "style_guide",
                "chapter_notes",
            ],
            "properties": {
                "chapter_id": _string_schema(),
                "chunk_id": _string_schema(min_length=1),
                "chunk_ids": _string_array_schema(),
                "block_ids": _string_array_schema(),
                "source_text": _string_schema(min_length=1),
                "context_before": _string_schema(),
                "context_after": _string_schema(),
                "footnote_markers": _string_array_schema(),
                "glossary": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["source", "target"],
                        "properties": {
                            "source": _string_schema(min_length=1),
                            "target": _string_schema(min_length=1),
                            "note": _string_schema(),
                        },
                    },
                },
                "style_hints": _string_array_schema(),
                "style_guide": _string_schema(),
                "chapter_notes": _string_schema(),
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
        "template_id": _string_schema(min_length=1),
        "template_version": {"type": "integer", "minimum": 1},
        "job_id": _string_schema(min_length=1),
        "input_json_path": _string_schema(min_length=1),
        "output_json_path": _string_schema(min_length=1),
        "output_schema_version": {"type": "string", "const": OUTPUT_SCHEMA_VERSION},
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


def get_prompts_dir() -> Path:
    """Return repository prompts directory."""

    return Path(__file__).resolve().parents[4] / "prompts"


def get_prompt_template_spec(template_id: str) -> PromptTemplateSpec:
    """Return template specification or raise ValueError."""

    spec = PROMPT_TEMPLATE_SPECS.get(template_id)
    if spec is None:
        available = ", ".join(sorted(PROMPT_TEMPLATE_SPECS))
        raise ValueError(f"Unknown template_id '{template_id}'. Available templates: {available}")
    return spec


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


def build_prompt_template_payload(
    job_id: str,
    input_json_path: Path,
    output_json_path: Path,
    template_id: str = "translate_chunk",
) -> dict[str, Any]:
    """Build structured prompt template payload for one job."""

    spec = get_prompt_template_spec(template_id)
    return {
        "schema_version": PROMPT_TEMPLATE_SCHEMA_VERSION,
        "template_id": template_id,
        "template_version": spec.template_version,
        "job_id": job_id,
        "input_json_path": str(input_json_path),
        "output_json_path": str(output_json_path),
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
    }


def render_prompt(template_payload: dict[str, Any], templates_dir: Path | None = None) -> str:
    """Render prompt markdown from template assets under prompts/."""

    errors = validate_prompt_template_payload(template_payload)
    if errors:
        message = "; ".join(errors)
        raise ValueError(f"Prompt template payload is invalid: {message}")

    spec = get_prompt_template_spec(str(template_payload["template_id"]))
    template_path = (templates_dir or get_prompts_dir()) / spec.filename
    if not template_path.exists():
        raise ValueError(f"Prompt template file does not exist: {template_path}")

    template_text = template_path.read_text(encoding="utf-8")
    output_schema_json = json.dumps(spec.output_schema, indent=2, ensure_ascii=False)
    output_skeleton_json = json.dumps(
        build_output_skeleton(template_id=spec.template_id, job_id=str(template_payload["job_id"])),
        indent=2,
        ensure_ascii=False,
    )

    replacements = {
        "{{prompt_schema_version}}": PROMPT_TEMPLATE_SCHEMA_VERSION,
        "{{template_id}}": spec.template_id,
        "{{template_version}}": str(spec.template_version),
        "{{job_id}}": str(template_payload["job_id"]),
        "{{input_json_path}}": str(template_payload["input_json_path"]),
        "{{output_json_path}}": str(template_payload["output_json_path"]),
        "{{output_schema_version}}": OUTPUT_SCHEMA_VERSION,
        "{{output_schema_json}}": output_schema_json,
        "{{output_skeleton_json}}": output_skeleton_json,
    }

    rendered = template_text
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)

    if "{{" in rendered or "}}" in rendered:
        raise ValueError(f"Prompt template has unresolved placeholders: {template_path}")

    return rendered


def render_codex_prompt_markdown(template_payload: dict[str, Any]) -> str:
    """Backward-compatible alias for prompt rendering."""

    return render_prompt(template_payload)


def build_output_skeleton(template_id: str, job_id: str) -> dict[str, Any]:
    """Build output.json skeleton per template."""

    base: dict[str, Any] = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "template_id": template_id,
        "job_id": job_id,
        "status": "ok",
        "notes": [],
        "errors": [],
    }

    if template_id == "translate_chunk":
        base.update(
            {
                "chunk_id": "<from input.payload.chunk_id>",
                "block_ids": ["<from input.payload.block_ids>"],
                "translated_text": "<translated text>",
                "preserved_footnote_markers": ["<all markers preserved exactly>"],
            }
        )
    elif template_id == "editorial_pass":
        base.update(
            {
                "chunk_id": "<from input.payload.chunk_id>",
                "block_ids": ["<from input.payload.block_ids>"],
                "edited_text": "<edited text>",
                "preserved_footnote_markers": ["<all markers preserved exactly>"],
                "editorial_actions": [{"action": "<brief action>", "reason": "<why>"}],
            }
        )
    elif template_id == "terminology_check":
        base.update(
            {
                "chunk_id": "<from input.payload.chunk_id>",
                "block_ids": ["<from input.payload.block_ids>"],
                "preserved_footnote_markers": ["<all markers preserved exactly>"],
                "terminology_passed": True,
                "violations": [],
            }
        )
    elif template_id == "semantic_qa":
        base.update(
            {
                "chunk_id": "<from input.payload.chunk_id>",
                "block_ids": ["<from input.payload.block_ids>"],
                "preserved_footnote_markers": ["<all markers preserved exactly>"],
                "qa_passed": True,
                "issues": [],
            }
        )
    elif template_id == "chapter_summary":
        base.update(
            {
                "chapter_id": "<from input.payload.chapter_id>",
                "chunk_ids": ["<from input.payload.chunk_ids>"],
                "block_ids": ["<from input.payload.block_ids>"],
                "summary_markdown": "<concise summary>",
                "key_points": ["<point 1>", "<point 2>"],
                "preserved_footnote_markers": ["<all markers preserved exactly>"],
            }
        )
    elif template_id == "glossary_update_proposal":
        base.update(
            {
                "chapter_id": "<from input.payload.chapter_id>",
                "chunk_ids": ["<from input.payload.chunk_ids>"],
                "block_ids": ["<from input.payload.block_ids>"],
                "preserved_footnote_markers": ["<all markers preserved exactly>"],
                "proposals": [
                    {
                        "source_term": "<term>",
                        "suggested_target": "<target term>",
                        "rationale": "<why>",
                        "evidence_chunk_ids": ["<chunk id>"],
                    }
                ],
            }
        )
    else:
        raise ValueError(f"Unsupported template_id for skeleton: {template_id}")

    return base


def validate_prompt_template_payload(payload: dict[str, Any]) -> list[str]:
    """Validate prompt template payload shape."""

    errors = _validate_against_schema(payload, PROMPT_TEMPLATE_SCHEMA, path="prompt")
    template_id = payload.get("template_id") if isinstance(payload, dict) else None
    if isinstance(template_id, str) and template_id in PROMPT_TEMPLATE_SPECS:
        expected_version = PROMPT_TEMPLATE_SPECS[template_id].template_version
        if payload.get("template_version") != expected_version:
            errors.append(
                f"prompt.template_version must be {expected_version} for template_id '{template_id}'"
            )
    elif isinstance(template_id, str):
        available = ", ".join(sorted(PROMPT_TEMPLATE_SPECS))
        errors.append(f"prompt.template_id must be one of: {available}")

    return errors


def validate_input_payload(payload: Any) -> list[str]:
    """Validate input.json against strict contract checks."""

    return _validate_against_schema(payload, INPUT_JSON_SCHEMA, path="input")


def validate_output_payload(
    payload: Any,
    expected_job_id: str | None = None,
    expected_template_id: str | None = "translate_chunk",
) -> list[str]:
    """Strictly validate output payload contract."""

    if not isinstance(payload, dict):
        return ["output payload root must be an object"]

    template_id = payload.get("template_id")
    errors: list[str] = []

    if not isinstance(template_id, str) or not template_id:
        errors.append("output.template_id must be a non-empty string")
        template_id = expected_template_id

    if expected_template_id is not None and template_id != expected_template_id:
        errors.append(f"output.template_id does not match expected template id '{expected_template_id}'")

    schema = PROMPT_OUTPUT_SCHEMAS.get(str(template_id))
    if schema is None:
        available = ", ".join(sorted(PROMPT_OUTPUT_SCHEMAS))
        errors.append(f"output.template_id must be one of: {available}")
        return errors

    errors.extend(_validate_against_schema(payload, schema, path="output"))

    if expected_job_id is not None and payload.get("job_id") != expected_job_id:
        errors.append("output.job_id does not match expected job id")

    status = payload.get("status")
    output_errors = payload.get("errors")
    if status == "failed" and isinstance(output_errors, list) and len(output_errors) == 0:
        errors.append("output.errors must contain at least one message when status is 'failed'")

    if status == "ok":
        if template_id == "translate_chunk" and not str(payload.get("translated_text", "")).strip():
            errors.append("output.translated_text must be non-empty when status is 'ok'")
        if template_id == "editorial_pass" and not str(payload.get("edited_text", "")).strip():
            errors.append("output.edited_text must be non-empty when status is 'ok'")

    return errors


def load_and_validate_output_json(
    output_json_path: Path,
    expected_job_id: str | None,
    expected_template_id: str | None = "translate_chunk",
) -> OutputLoadResult:
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

    validation_errors = validate_output_payload(
        payload,
        expected_job_id=expected_job_id,
        expected_template_id=expected_template_id,
    )
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
    block_ids: list[str] | None = None,
    footnote_markers: list[str] | None = None,
    style_guide: str = "",
    chapter_notes: str = "",
    chapter_id: str = "",
    chunk_ids: list[str] | None = None,
    template_id: str = "translate_chunk",
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

    _ = get_prompt_template_spec(template_id)

    paths = build_codex_job_paths(workspace_root, book_id, job_id)
    paths.job_dir.mkdir(parents=True, exist_ok=True)

    normalized_block_ids = [str(item) for item in (block_ids or [])]
    normalized_chunk_ids = [str(item) for item in (chunk_ids or [])]

    input_payload = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "job": {
            "book_id": book_id,
            "job_id": job_id,
            "template_id": template_id,
            "created_at": utcnow_iso(),
            "source_language": source_language,
            "target_language": target_language,
            "output_path": str(paths.output_json),
        },
        "payload": {
            "chapter_id": chapter_id,
            "chunk_id": chunk_id,
            "chunk_ids": normalized_chunk_ids,
            "block_ids": normalized_block_ids,
            "source_text": source_text,
            "context_before": context_before,
            "context_after": context_after,
            "footnote_markers": [str(item) for item in (footnote_markers or [])],
            "glossary": _normalize_glossary(glossary or []),
            "style_hints": [str(item) for item in (style_hints or [])],
            "style_guide": str(style_guide),
            "chapter_notes": str(chapter_notes),
        },
    }

    input_errors = validate_input_payload(input_payload)
    if input_errors:
        raise ValueError(f"input payload is invalid: {'; '.join(input_errors)}")

    prompt_template_payload = build_prompt_template_payload(
        job_id=job_id,
        input_json_path=paths.input_json,
        output_json_path=paths.output_json,
        template_id=template_id,
    )
    prompt_text = render_prompt(prompt_template_payload)

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


def _validate_against_schema(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must be {schema['const']!r}")
        return errors

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(repr(item) for item in schema["enum"])
        errors.append(f"{path} must be one of: {allowed}")

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            errors.append(f"{path} must be an object")
            return errors

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        missing = required - set(value.keys())
        if missing:
            missing_list = ", ".join(sorted(missing))
            errors.append(f"{path} is missing required fields: {missing_list}")

        if schema.get("additionalProperties", True) is False:
            extra = set(value.keys()) - set(properties.keys())
            if extra:
                extra_list = ", ".join(sorted(extra))
                errors.append(f"{path} has unexpected fields: {extra_list}")

        for key, child_schema in properties.items():
            if key in value:
                errors.extend(_validate_against_schema(value[key], child_schema, f"{path}.{key}"))

        return errors

    if schema_type == "array":
        if not isinstance(value, list):
            errors.append(f"{path} must be an array")
            return errors

        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_against_schema(item, items_schema, f"{path}[{index}]"))
        return errors

    if schema_type == "string":
        if not isinstance(value, str):
            errors.append(f"{path} must be a string")
            return errors

        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path} must be at least {min_length} characters")
        return errors

    if schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{path} must be an integer")
            return errors

        minimum = schema.get("minimum")
        if isinstance(minimum, int) and value < minimum:
            errors.append(f"{path} must be >= {minimum}")
        return errors

    if schema_type == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path} must be a boolean")
        return errors

    return errors


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
