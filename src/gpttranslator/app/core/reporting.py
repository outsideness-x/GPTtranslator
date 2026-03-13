"""Local pipeline reporting helpers for status/summary/run logs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..translation.protocol import utcnow_iso
from .manifest import load_book_manifest


@dataclass(frozen=True, slots=True)
class BookRunSummary:
    """Aggregate local metrics used by status and summary reports."""

    book_id: str
    page_count: int
    block_count: int
    chunk_count: int
    codex_jobs_count: int
    retries_count: int
    qa_flags_count: int
    build_pdf_status: str
    stage_statuses: dict[str, str]


def ensure_codex_logs(book_root: Path) -> tuple[Path, Path]:
    """Ensure Codex JSONL logs exist for local observability."""

    logs_dir = book_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    jobs_path = logs_dir / "codex_jobs.jsonl"
    failures_path = logs_dir / "codex_failures.jsonl"
    jobs_path.touch(exist_ok=True)
    failures_path.touch(exist_ok=True)
    return jobs_path, failures_path


def append_run_log(
    *,
    book_root: Path,
    stage: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> Path:
    """Append one structured line into logs/run.log."""

    logs_dir = book_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_log_path = logs_dir / "run.log"
    payload: dict[str, Any] = {
        "timestamp": utcnow_iso(),
        "book_id": book_root.name,
        "stage": stage,
        "status": status,
        "message": message,
    }
    if details:
        payload["details"] = details
    with run_log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return run_log_path


def collect_book_run_summary(book_root: Path) -> BookRunSummary:
    """Build summary metrics strictly from local filesystem artifacts."""

    analysis_dir = book_root / "analysis"
    translated_dir = book_root / "translated"
    output_dir = book_root / "output"
    logs_dir = book_root / "logs"
    manifest_path = book_root / "manifest.json"

    manifest_metadata: dict[str, Any] = {}
    extraction_meta: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = load_book_manifest(manifest_path)
            manifest_metadata = manifest.metadata if isinstance(manifest.metadata, dict) else {}
            extraction_raw = manifest_metadata.get("extraction")
            if isinstance(extraction_raw, dict):
                extraction_meta = extraction_raw
        except Exception:
            manifest_metadata = {}
            extraction_meta = {}

    page_count = _jsonl_count(analysis_dir / "pages.jsonl")
    if page_count == 0:
        page_count = _safe_int(extraction_meta.get("page_count"))

    block_count = _jsonl_count(analysis_dir / "blocks.jsonl")
    if block_count == 0:
        block_count = _safe_int(extraction_meta.get("block_count"))

    chunk_count = _jsonl_count(analysis_dir / "chunks.jsonl")
    if chunk_count == 0:
        chunk_count = _safe_int(extraction_meta.get("chunk_count"))

    codex_rows = _jsonl_rows(logs_dir / "codex_jobs.jsonl")
    codex_jobs_count = len(codex_rows)
    retries_count = 0
    for row in codex_rows:
        attempts = _safe_int(row.get("attempt_count"), default=1)
        retries_count += max(0, attempts - 1)

    qa_flags_count = _jsonl_count(translated_dir / "qa_flags.jsonl")

    translated_pdf_path = output_dir / "translated_book.pdf"
    build_pdf_status = "built" if translated_pdf_path.exists() else "pending"

    stage_statuses = _resolve_stage_statuses(book_root=book_root, manifest_metadata=manifest_metadata)

    return BookRunSummary(
        book_id=book_root.name,
        page_count=page_count,
        block_count=block_count,
        chunk_count=chunk_count,
        codex_jobs_count=codex_jobs_count,
        retries_count=retries_count,
        qa_flags_count=qa_flags_count,
        build_pdf_status=build_pdf_status,
        stage_statuses=stage_statuses,
    )


def write_translation_summary(book_root: Path, summary: BookRunSummary | None = None) -> Path:
    """Write output/translation_summary.md from local pipeline data."""

    output_dir = book_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = summary or collect_book_run_summary(book_root)
    path = output_dir / "translation_summary.md"

    qa_report_path = output_dir / "qa_report.md"
    build_report_path = output_dir / "build_report.md"
    translated_pdf_path = output_dir / "translated_book.pdf"
    run_log_path = book_root / "logs" / "run.log"
    codex_jobs_path = book_root / "logs" / "codex_jobs.jsonl"

    lines: list[str] = [
        f"# Translation Summary: {result.book_id}",
        "",
        "## Metrics",
        "",
        f"- Pages: **{result.page_count}**",
        f"- Blocks: **{result.block_count}**",
        f"- Chunks: **{result.chunk_count}**",
        f"- Codex jobs: **{result.codex_jobs_count}**",
        f"- Retries: **{result.retries_count}**",
        f"- QA flags: **{result.qa_flags_count}**",
        f"- PDF build status: **{result.build_pdf_status}**",
        "",
        "## Stage Status",
        "",
        "| Stage | Status |",
        "|---|---|",
    ]
    for stage in ("init", "inspect", "extract", "translate", "qa", "build"):
        lines.append(f"| {stage} | {result.stage_statuses.get(stage, 'pending')} |")

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- `output/translation_summary.md`: `{path.exists()}`",
            f"- `output/qa_report.md`: `{qa_report_path.exists()}`",
            f"- `output/build_report.md`: `{build_report_path.exists()}`",
            f"- `output/translated_book.pdf`: `{translated_pdf_path.exists()}`",
            f"- `logs/run.log`: `{run_log_path.exists()}`",
            f"- `logs/codex_jobs.jsonl`: `{codex_jobs_path.exists()}`",
            "",
            f"_Generated at {utcnow_iso()}_",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _resolve_stage_statuses(*, book_root: Path, manifest_metadata: dict[str, Any]) -> dict[str, str]:
    pipeline_raw = manifest_metadata.get("pipeline")
    pipeline = pipeline_raw if isinstance(pipeline_raw, dict) else {}

    def _pipeline_value(stage: str) -> str:
        raw = pipeline.get(stage, "pending")
        value = str(raw).strip().lower() if raw is not None else "pending"
        return value or "pending"

    status: dict[str, str] = {
        "init": "done"
        if (book_root / "manifest.json").exists() and (book_root / "input" / "original.pdf").exists()
        else "pending",
        "inspect": _pipeline_value("inspect"),
        "extract": _pipeline_value("extract"),
        "translate": _pipeline_value("translate"),
        "qa": _pipeline_value("qa"),
        "build": _pipeline_value("build"),
    }

    if (book_root / "analysis" / "inspection_report.json").exists():
        status["inspect"] = "done"
    if (book_root / "analysis" / "chunks.jsonl").exists() and (book_root / "analysis" / "document_graph.json").exists():
        status["extract"] = "done"
    if _has_completed_rows(book_root / "translated" / "translated_chunks.jsonl"):
        status["translate"] = "done"
    if (book_root / "translated" / "qa_flags.jsonl").exists() and (book_root / "output" / "qa_report.md").exists():
        status["qa"] = "done"
    if (book_root / "output" / "translated_book.pdf").exists() and (book_root / "output" / "build_report.md").exists():
        status["build"] = "done"
    return status


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if raw_line.strip():
            count += 1
    return count


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _has_completed_rows(path: Path) -> bool:
    for row in _jsonl_rows(path):
        if str(row.get("status", "")).lower() == "completed":
            return True
    return False


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
