"""Tests for file-based Codex protocol contract and recovery policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.translation.backends.codex_cli import CodexCliBackend
from gpttranslator.app.translation.protocol import (
    INPUT_SCHEMA_VERSION,
    OUTPUT_SCHEMA_VERSION,
    build_codex_job_paths,
    create_codex_job,
    validate_output_payload,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MOCK_CODEX_CLI = FIXTURES_DIR / "mock_codex_cli.py"
EXAMPLE_JOB_DIR = FIXTURES_DIR / "codex_job_example"


def _build_backend(mock_script: Path, timeout_seconds: int = 1, max_attempts: int = 2) -> CodexCliBackend:
    return CodexCliBackend(
        codex_command="codex",
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        command_builder=lambda job: [
            sys.executable,
            str(mock_script),
            "--job-dir",
            str(Path(job.output_path).parent),
            "--job-id",
            job.job_id,
        ],
    )


def test_create_codex_job_creates_full_contract_layout(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    job = create_codex_job(
        workspace_root=workspace_root,
        book_id="book-1",
        job_id="job-1",
        chunk_id="chunk-1",
        source_text="Hello world",
        glossary=[{"source": "world", "target": "mir"}],
    )

    paths = build_codex_job_paths(workspace_root=workspace_root, book_id="book-1", job_id="job-1")

    assert paths.job_dir.exists()
    assert paths.input_json.exists()
    assert paths.prompt_md.exists()
    assert paths.output_json.exists()
    assert paths.raw_stdout.exists()
    assert paths.raw_stderr.exists()
    assert paths.meta_json.exists()

    input_payload = json.loads(paths.input_json.read_text(encoding="utf-8"))
    assert input_payload["schema_version"] == INPUT_SCHEMA_VERSION
    assert input_payload["job"]["job_id"] == "job-1"
    assert input_payload["job"]["output_path"] == str(paths.output_json)

    prompt_text = paths.prompt_md.read_text(encoding="utf-8")
    assert str(paths.input_json) in prompt_text
    assert str(paths.output_json) in prompt_text
    assert OUTPUT_SCHEMA_VERSION in prompt_text

    meta_payload = json.loads(paths.meta_json.read_text(encoding="utf-8"))
    assert meta_payload["status"] == "queued"
    assert meta_payload["job_id"] == "job-1"
    assert meta_payload["attempts"] == []

    assert job.output_path == str(paths.output_json)
    assert job.raw_stdout_path == str(paths.raw_stdout)
    assert job.raw_stderr_path == str(paths.raw_stderr)
    assert job.meta_path == str(paths.meta_json)


def test_validate_output_payload_is_strict() -> None:
    valid_payload = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "job_id": "job-1",
        "status": "ok",
        "translated_text": "translated",
        "notes": [],
        "errors": [],
    }
    assert validate_output_payload(valid_payload, expected_job_id="job-1") == []

    invalid_payload = dict(valid_payload)
    invalid_payload["unexpected"] = "field"
    errors = validate_output_payload(invalid_payload, expected_job_id="job-1")
    assert any("unexpected fields" in error for error in errors)

    wrong_job_id_payload = dict(valid_payload)
    wrong_job_id_payload["job_id"] = "job-2"
    errors = validate_output_payload(wrong_job_id_payload, expected_job_id="job-1")
    assert any("does not match expected job id" in error for error in errors)


@pytest.mark.parametrize(
    ("scenario", "expected_first_outcome"),
    [
        ("invalid_then_valid", "invalid_json"),
        ("partial_then_valid", "partial_json"),
        ("missing_then_valid", "missing_output_file"),
        ("timeout_then_valid", "timeout"),
        ("interrupt_then_valid", "interrupted_process"),
    ],
)
def test_backend_recovery_policy_retries_and_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_first_outcome: str,
) -> None:
    monkeypatch.setenv("MOCK_CODEX_SCENARIO", scenario)
    monkeypatch.setenv("MOCK_CODEX_TIMEOUT_SLEEP", "2.0")

    job = create_codex_job(
        workspace_root=tmp_path / "workspace",
        book_id="book-1",
        job_id=f"job-{scenario}",
        chunk_id="chunk-1",
        source_text="This is a test sentence.",
        timeout_seconds=1,
        max_attempts=2,
    )

    backend = _build_backend(MOCK_CODEX_CLI, timeout_seconds=1, max_attempts=2)
    result = backend.run_job(job)

    assert result.success is True
    assert result.attempt_count == 2

    meta_payload = json.loads(Path(job.meta_path).read_text(encoding="utf-8"))
    assert meta_payload["status"] == "succeeded"
    assert len(meta_payload["attempts"]) == 2
    assert meta_payload["attempts"][0]["outcome"] == expected_first_outcome
    assert meta_payload["attempts"][0]["retry_scheduled"] is True
    assert meta_payload["attempts"][1]["outcome"] == "success"

    output_payload = json.loads(Path(job.output_path).read_text(encoding="utf-8"))
    assert output_payload["schema_version"] == OUTPUT_SCHEMA_VERSION
    assert output_payload["job_id"] == job.job_id
    assert output_payload["status"] == "ok"

    stdout_log = Path(job.raw_stdout_path).read_text(encoding="utf-8")
    stderr_log = Path(job.raw_stderr_path).read_text(encoding="utf-8")
    assert "attempt 1" in stdout_log
    assert "attempt 2" in stdout_log
    assert "attempt 1" in stderr_log
    assert "attempt 2" in stderr_log


def test_backend_fails_after_retries_when_output_schema_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_CODEX_SCENARIO", "schema_invalid")

    job = create_codex_job(
        workspace_root=tmp_path / "workspace",
        book_id="book-1",
        job_id="job-schema-invalid",
        chunk_id="chunk-1",
        source_text="Schema validation test.",
        timeout_seconds=1,
        max_attempts=2,
    )

    backend = _build_backend(MOCK_CODEX_CLI, timeout_seconds=1, max_attempts=2)
    result = backend.run_job(job)

    assert result.success is False
    assert result.failure_reason == "output_schema_validation_failed"
    assert result.attempt_count == 2

    meta_payload = json.loads(Path(job.meta_path).read_text(encoding="utf-8"))
    assert meta_payload["status"] == "failed"
    assert len(meta_payload["attempts"]) == 2
    assert meta_payload["attempts"][0]["outcome"] == "output_schema_validation_failed"
    assert meta_payload["attempts"][1]["outcome"] == "output_schema_validation_failed"


def test_mock_example_files_match_output_schema() -> None:
    required_files = {
        "input.json",
        "prompt.md",
        "output.json",
        "raw_stdout.txt",
        "raw_stderr.txt",
        "meta.json",
    }
    assert required_files.issubset({path.name for path in EXAMPLE_JOB_DIR.iterdir()})

    output_payload = json.loads((EXAMPLE_JOB_DIR / "output.json").read_text(encoding="utf-8"))
    errors = validate_output_payload(output_payload, expected_job_id="job-0001")
    assert errors == []
