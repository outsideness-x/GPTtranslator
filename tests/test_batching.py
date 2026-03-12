"""Tests for batch processing, checkpointing, and resume flows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.core.models import Chunk
from gpttranslator.app.translation.batching import (
    BatchManifest,
    BatchRecord,
    BatchRunOptions,
    build_batch_manifest,
    load_batch_manifest,
    run_batch_translation,
    save_batch_manifest,
    select_batches_for_run,
)
from gpttranslator.app.translation.codex_backend import MockCodexBackend
from gpttranslator.app.translation.codex_backend import ChunkTranslationResult
from gpttranslator.app.translation.economy.complexity import ComplexityAssessment, ComplexityFeatures
from gpttranslator.app.translation.economy.planner import ChunkPlan
from gpttranslator.app.translation.economy.prefilter import PreFilterDecision
from gpttranslator.app.core.models import CodexResult


def _plan(chunk_id: str, chapter_id: str | None, action: str = "codex") -> ChunkPlan:
    chunk = Chunk(
        chunk_id=chunk_id,
        chapter_id=chapter_id,
        page_range=(1, 1),
        block_ids=[f"block-{chunk_id}"],
        chunk_type="paragraph_group",
        source_text=f"Source text for {chunk_id}.",
        footnote_refs=[],
    )
    complexity = ComplexityAssessment(
        score=0.5,
        features=ComplexityFeatures(
            char_count=len(chunk.source_text),
            footnote_markers=0,
            rare_term_count=0,
            digit_ratio=0.0,
            formula_ratio=0.0,
            list_density=0.0,
            table_like=False,
            unusual_layout=False,
        ),
        risk_flags=(),
    )
    prefilter = PreFilterDecision(action="codex", reason="requires_model_translation")
    return ChunkPlan(
        chunk=chunk,
        action=action,  # type: ignore[arg-type]
        reason="test",
        tier="B",
        complexity=complexity,
        template_id="translate_chunk",
        context_package=None,
        fingerprint=None,
        run_editorial=False,
        run_semantic_qa=False,
        cache_hit_output=None,
        prefilter=prefilter,
    )


def test_build_batch_manifest_groups_by_chapter_and_range() -> None:
    plans = [
        _plan("chunk-1", "chapter-01"),
        _plan("chunk-2", "chapter-01"),
        _plan("chunk-3", "chapter-01"),
        _plan("chunk-4", "chapter-02"),
        _plan("chunk-5", None),
        _plan("chunk-6", None),
    ]
    manifest = build_batch_manifest(book_id="book-1", plans=plans, max_chunks_per_batch=2)

    assert manifest.book_id == "book-1"
    assert len(manifest.batches) == 4
    assert manifest.batches[0].chunk_ids == ["chunk-1", "chunk-2"]
    assert manifest.batches[1].chunk_ids == ["chunk-3"]
    assert manifest.batches[2].chunk_ids == ["chunk-4"]
    assert manifest.batches[3].chunk_ids == ["chunk-5", "chunk-6"]
    assert all(batch.status == "pending" for batch in manifest.batches)


def test_select_batches_for_resume_and_failed_filters() -> None:
    manifest = BatchManifest(
        schema_version="gpttranslator.translation.batch_manifest.v1",
        book_id="book-1",
        strategy="chapter_then_chunk_range",
        created_at="2026-03-13T00:00:00+00:00",
        updated_at="2026-03-13T00:00:00+00:00",
        batches=[
            BatchRecord(batch_id="batch-1", chunk_ids=["c1"], status="completed"),
            BatchRecord(batch_id="batch-2", chunk_ids=["c2"], status="failed"),
            BatchRecord(batch_id="batch-3", chunk_ids=["c3"], status="pending"),
            BatchRecord(batch_id="batch-4", chunk_ids=["c4"], status="running"),
        ],
    )

    resume_selected = select_batches_for_run(
        manifest=manifest,
        options=BatchRunOptions(resume=True),
    )
    assert [item.batch_id for item in resume_selected] == ["batch-2", "batch-3", "batch-4"]

    failed_selected = select_batches_for_run(
        manifest=manifest,
        options=BatchRunOptions(resume=True, only_failed=True),
    )
    assert [item.batch_id for item in failed_selected] == ["batch-2"]

    ranged = select_batches_for_run(
        manifest=manifest,
        options=BatchRunOptions(from_batch="batch-2", to_batch="batch-3"),
    )
    assert [item.batch_id for item in ranged] == ["batch-2", "batch-3"]


def test_run_batch_translation_supports_resume_only_failed(tmp_path: Path) -> None:
    book_root = tmp_path / "workspace" / "book-1"
    translated_dir = book_root / "translated"
    logs_dir = book_root / "logs"
    translated_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    plans = [
        _plan("chunk-1", "chapter-01"),
        _plan("chunk-2", "chapter-01"),
        _plan("chunk-3", "chapter-01"),
    ]

    first_backend = MockCodexBackend(fail_on_chunk_ids={"chunk-2"})
    first_result = run_batch_translation(
        book_id="book-1",
        plans=plans,
        translated_dir=translated_dir,
        logs_dir=logs_dir,
        backend=first_backend,
        options=BatchRunOptions(resume=False, max_chunks_per_batch=3),
        timeout_seconds=1,
        max_attempts=1,
        strict_json=True,
    )
    assert first_result.failed_chunks == 1
    assert (translated_dir / "batch_manifest.json").exists()
    assert (translated_dir / "chunk_checkpoints.json").exists()
    assert first_result.translated_chunks_path.exists()
    assert first_result.codex_jobs_log_path.exists()
    assert first_result.codex_failures_log_path.exists()
    assert first_result.codex_failures_log_path.read_text(encoding="utf-8").strip()

    checkpoint_payload = json.loads((translated_dir / "chunk_checkpoints.json").read_text(encoding="utf-8"))
    assert checkpoint_payload["chunks"]["chunk-2"]["status"] == "failed"
    assert checkpoint_payload["chunks"]["chunk-1"]["status"] == "completed"
    assert checkpoint_payload["chunks"]["chunk-3"]["status"] == "completed"

    manifest = load_batch_manifest(translated_dir / "batch_manifest.json")
    assert manifest.batches[0].status == "failed"

    second_backend = MockCodexBackend()
    second_result = run_batch_translation(
        book_id="book-1",
        plans=plans,
        translated_dir=translated_dir,
        logs_dir=logs_dir,
        backend=second_backend,
        options=BatchRunOptions(resume=True, only_failed=True, max_chunks_per_batch=3),
        timeout_seconds=1,
        max_attempts=1,
        strict_json=True,
    )
    assert second_result.total_target_chunks == 1
    assert second_result.processed_chunks == 1
    assert second_result.failed_chunks == 0

    resumed_checkpoint = json.loads((translated_dir / "chunk_checkpoints.json").read_text(encoding="utf-8"))
    assert resumed_checkpoint["chunks"]["chunk-2"]["status"] == "completed"
    resumed_manifest = load_batch_manifest(translated_dir / "batch_manifest.json")
    assert resumed_manifest.batches[0].status == "completed"


def test_manifest_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "batch_manifest.json"
    manifest = BatchManifest(
        schema_version="gpttranslator.translation.batch_manifest.v1",
        book_id="book-rt",
        strategy="chapter_then_chunk_range",
        created_at="2026-03-13T00:00:00+00:00",
        updated_at="2026-03-13T00:00:00+00:00",
        batches=[BatchRecord(batch_id="batch-0001", chunk_ids=["c1", "c2"])],
    )
    save_batch_manifest(path, manifest)
    loaded = load_batch_manifest(path)
    assert loaded.book_id == "book-rt"
    assert loaded.batches[0].chunk_ids == ["c1", "c2"]


def test_select_batches_raises_for_unknown_batch_id() -> None:
    manifest = BatchManifest(
        schema_version="gpttranslator.translation.batch_manifest.v1",
        book_id="book-1",
        strategy="chapter_then_chunk_range",
        created_at="2026-03-13T00:00:00+00:00",
        updated_at="2026-03-13T00:00:00+00:00",
        batches=[BatchRecord(batch_id="batch-1", chunk_ids=["c1"])],
    )
    with pytest.raises(ValueError, match="Unknown batch id"):
        select_batches_for_run(manifest=manifest, options=BatchRunOptions(from_batch="batch-404"))


def test_batch_runner_best_effort_json_allows_non_strict_mode(tmp_path: Path) -> None:
    class _BestEffortBackend:
        def translate_chunk(self, request):  # type: ignore[no-untyped-def]
            output_path = request.workspace_root / request.book_id / "jobs" / "best-effort" / "output.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps({"translated_text": "best effort text"}), encoding="utf-8")
            return ChunkTranslationResult(
                job=type(
                    "J",
                    (),
                    {"job_id": "job-best", "output_path": str(output_path)},
                )(),
                result=CodexResult(
                    job_id="job-best",
                    return_code=0,
                    stdout="",
                    stderr="",
                    success=False,
                    output_path=str(output_path),
                    failure_reason="output_schema_validation_failed",
                    meta_path=None,
                    attempt_count=1,
                ),
                output_payload=None,
            )

    book_root = tmp_path / "workspace" / "book-nonstrict"
    translated_dir = book_root / "translated"
    logs_dir = book_root / "logs"
    translated_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    result = run_batch_translation(
        book_id="book-nonstrict",
        plans=[_plan("chunk-1", "chapter-01")],
        translated_dir=translated_dir,
        logs_dir=logs_dir,
        backend=_BestEffortBackend(),
        options=BatchRunOptions(resume=False, max_chunks_per_batch=2),
        timeout_seconds=1,
        max_attempts=1,
        strict_json=False,
    )
    assert result.completed_chunks == 1
    checkpoint_payload = json.loads((translated_dir / "chunk_checkpoints.json").read_text(encoding="utf-8"))
    assert checkpoint_payload["chunks"]["chunk-1"]["status"] == "completed"
