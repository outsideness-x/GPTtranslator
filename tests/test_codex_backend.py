"""Tests for high-level Codex CLI translation backend."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.core.models import Chunk
from gpttranslator.app.translation.codex_backend import (
    BackendUnavailableError,
    ChunkTranslationRequest,
    CodexCliBackend,
    MockCodexBackend,
    build_translation_backend,
    parse_backend_name,
)
from gpttranslator.app.translation.protocol import load_and_validate_output_json

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MOCK_CODEX_CLI = FIXTURES_DIR / "mock_codex_cli.py"


def _chunk(chunk_id: str = "chunk-1") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        chapter_id="chapter-01",
        page_range=(1, 1),
        block_ids=["block-1", "block-2"],
        chunk_type="paragraph_group",
        source_text="This is a test sentence with marker [1].",
        local_context_before="Context before.",
        local_context_after="Context after.",
        footnote_refs=[{"marker": "[1]"}],
        glossary_hints=["term"],
    )


def test_prepare_chunk_job_builds_file_contract_and_prompt(tmp_path: Path) -> None:
    backend = CodexCliBackend(dry_run=True)
    request = ChunkTranslationRequest(
        workspace_root=tmp_path / "workspace",
        book_id="book-1",
        chunk=_chunk("chunk-prepare"),
        glossary=[{"source": "sentence", "target": "предложение"}],
        style_guide="- Keep academic register.",
        chapter_notes="- Preserve marker fidelity.",
    )

    job = backend.prepare_chunk_job(request)
    job_dir = Path(job.output_path).parent

    assert (job_dir / "input.json").exists()
    assert (job_dir / "prompt.md").exists()
    assert (job_dir / "output.json").exists()
    assert (job_dir / "meta.json").exists()
    assert (job_dir / "raw_stdout.txt").exists()
    assert (job_dir / "raw_stderr.txt").exists()

    prompt_text = (job_dir / "prompt.md").read_text(encoding="utf-8")
    assert "translate_chunk" in prompt_text
    assert str(job_dir / "input.json") in prompt_text
    assert str(job_dir / "output.json") in prompt_text
    assert "footnote markers" in prompt_text.lower()


def test_translate_chunk_dry_run_writes_valid_structured_output(tmp_path: Path) -> None:
    backend = CodexCliBackend(dry_run=True)
    request = ChunkTranslationRequest(
        workspace_root=tmp_path / "workspace",
        book_id="book-1",
        chunk=_chunk("chunk-dry"),
    )

    translated = backend.translate_chunk(request)

    assert translated.result.success is True
    assert translated.result.return_code == 0
    assert translated.output_payload is not None
    assert translated.output_payload["chunk_id"] == "chunk-dry"
    assert translated.output_payload["preserved_footnote_markers"] == ["[1]"]
    assert Path(translated.job.output_path).exists()
    assert Path(translated.job.meta_path).exists()


def test_translate_chunk_calls_subprocess_and_validates_file_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_CODEX_SCENARIO", "valid")
    backend = CodexCliBackend(
        codex_command="codex",
        timeout_seconds=2,
        max_attempts=1,
        command_builder=lambda job: [
            sys.executable,
            str(MOCK_CODEX_CLI),
            "--job-dir",
            str(Path(job.output_path).parent),
            "--job-id",
            job.job_id,
        ],
    )
    request = ChunkTranslationRequest(
        workspace_root=tmp_path / "workspace",
        book_id="book-1",
        chunk=_chunk("chunk-subprocess"),
    )

    translated = backend.translate_chunk(request)

    assert translated.result.success is True
    assert translated.output_payload is not None
    assert translated.output_payload["template_id"] == "translate_chunk"
    assert translated.output_payload["chunk_id"] == "chunk-subprocess"
    assert translated.output_payload["translated_text"].startswith("translated-attempt-")


def test_codex_backend_reports_clear_error_when_cli_is_missing() -> None:
    backend = CodexCliBackend(codex_command="codex-binary-that-does-not-exist")
    with pytest.raises(BackendUnavailableError, match="not available in PATH"):
        backend.ensure_available()


def test_mock_backend_writes_valid_output_json(tmp_path: Path) -> None:
    backend = CodexCliBackend(dry_run=True)
    request = ChunkTranslationRequest(
        workspace_root=tmp_path / "workspace",
        book_id="book-1",
        chunk=_chunk("chunk-mock"),
    )
    job = backend.prepare_chunk_job(request)

    mock_backend = MockCodexBackend()
    result = mock_backend.run_job(job)
    assert result.success is True

    output_validation = load_and_validate_output_json(
        Path(job.output_path),
        expected_job_id=job.job_id,
        expected_template_id="translate_chunk",
    )
    assert output_validation.payload is not None
    assert output_validation.payload["translated_text"].startswith("[MOCK_RU]")


def test_backend_factory_and_parser() -> None:
    assert parse_backend_name("codex-cli") == "codex-cli"
    assert parse_backend_name("mock") == "mock"
    with pytest.raises(ValueError, match="backend must be one of"):
        parse_backend_name("unsupported")

    codex_backend = build_translation_backend(backend="codex-cli", dry_run=True)
    assert codex_backend.backend_name == "codex-cli"
    mock_backend = build_translation_backend(backend="mock")
    assert mock_backend.backend_name == "mock"
