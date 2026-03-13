"""QA layer for translated chunks with optional Codex-assisted checks."""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from ..core.models import Chunk, QAFlag
from ..core.reporting import ensure_codex_logs
from ..memory.glossary_manager import GlossaryEntry, parse_glossary_entries
from ..translation.codex_backend import ChunkTranslationRequest
from ..translation.economy.context import slice_glossary_entries
from ..translation.protocol import utcnow_iso

Severity = Literal["low", "medium", "high"]
ProgressCallback = Callable[[str], None]

_URL_RE = re.compile(r"\b(?:https?://\S+|www\.\S+)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"),
    re.compile(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b",
        re.IGNORECASE,
    ),
)
_EQUATION_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*\s*=\s*[^,;\n]{1,64}")


@dataclass(frozen=True, slots=True)
class QAOptions:
    """Settings controlling local and optional codex-based QA stages."""

    codex_enabled: bool = False
    codex_on_risk_only: bool = True
    strict_json: bool = True
    strict_terminology: bool = True
    timeout_seconds: int = 90
    max_attempts: int = 2


@dataclass(frozen=True, slots=True)
class QAResult:
    """QA stage summary and artifact paths."""

    qa_flags_path: Path
    qa_report_path: Path
    source_artifact: str
    total_chunks: int
    translated_chunks: int
    missing_chunks: int
    local_flags_count: int
    codex_flags_count: int
    total_flags_count: int
    high_severity_count: int
    medium_severity_count: int
    low_severity_count: int
    codex_semantic_jobs: int
    codex_terminology_jobs: int
    codex_failed_jobs: int
    elapsed_seconds: float


def run_qa_pass(
    *,
    book_root: Path,
    options: QAOptions,
    backend: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> QAResult:
    """Run QA checks over translated artifacts and persist QA outputs."""

    if options.codex_enabled and backend is None:
        raise ValueError("backend is required when codex QA is enabled")

    analysis_chunks_path = book_root / "analysis" / "chunks.jsonl"
    translated_dir = book_root / "translated"
    logs_dir = book_root / "logs"
    output_dir = book_root / "output"

    qa_flags_path = translated_dir / "qa_flags.jsonl"
    qa_report_path = output_dir / "qa_report.md"
    codex_jobs_log_path = logs_dir / "codex_jobs.jsonl"
    codex_failures_log_path = logs_dir / "codex_failures.jsonl"
    ensure_codex_logs(book_root)

    chunks_map = _load_chunks_map(analysis_chunks_path)
    if not analysis_chunks_path.exists():
        raise ValueError(f"analysis chunks file not found: {analysis_chunks_path}")
    if not chunks_map:
        raise ValueError("analysis/chunks.jsonl is empty; nothing to QA")
    translated_map, source_artifact = _load_completed_translation_map(
        translated_path=translated_dir / "translated_chunks.jsonl",
        edited_path=translated_dir / "edited_chunks.jsonl",
    )

    glossary_entries, _ = parse_glossary_entries(book_root / "memory" / "glossary.md")
    style_guide = _safe_read_text(book_root / "memory" / "style_guide.md")
    chapter_notes = _safe_read_text(book_root / "memory" / "chapter_notes.md")

    started_at = time.monotonic()
    flags: list[dict[str, Any]] = []
    local_flags_count = 0
    codex_flags_count = 0

    expected_chunk_ids = list(chunks_map.keys())
    local_processed = 0

    for chunk_id in expected_chunk_ids:
        chunk = chunks_map[chunk_id]
        translated_row = translated_map.get(chunk_id)
        if translated_row is None:
            flags.append(
                _make_flag(
                    chunk_id=chunk_id,
                    severity="high",
                    message="Chunk is missing in translated artifacts.",
                    rule_id="missing_translation",
                    source="local",
                    details={"expected": True, "status": "missing"},
                )
            )
            local_flags_count += 1
            local_processed += 1
            _emit_progress_local(
                progress_callback=progress_callback,
                processed=local_processed,
                total=max(1, len(expected_chunk_ids)),
                flags_count=local_flags_count,
                started_at=started_at,
            )
            continue

        local_chunk_flags = _run_local_chunk_checks(chunk=chunk, translated_row=translated_row)
        local_flags_count += len(local_chunk_flags)
        flags.extend(local_chunk_flags)
        local_processed += 1

        _emit_progress_local(
            progress_callback=progress_callback,
            processed=local_processed,
            total=max(1, len(expected_chunk_ids)),
            flags_count=local_flags_count,
            started_at=started_at,
        )

    codex_semantic_jobs = 0
    codex_terminology_jobs = 0
    codex_failed_jobs = 0

    if options.codex_enabled and backend is not None:
        risky_chunks = _select_codex_candidates(
            chunks_map=chunks_map,
            translated_map=translated_map,
            local_flags=flags,
            codex_on_risk_only=options.codex_on_risk_only,
            glossary_entries=glossary_entries,
        )

        codex_processed = 0
        for chunk_id in risky_chunks:
            translated_row = translated_map.get(chunk_id)
            chunk_item = chunks_map.get(chunk_id)
            if translated_row is None or chunk_item is None:
                continue
            target_text = str(translated_row.get("target_text", ""))
            glossary_subset = _build_glossary_subset(chunk_item.source_text, glossary_entries)

            semantic_request = ChunkTranslationRequest(
                workspace_root=book_root.parent,
                book_id=book_root.name,
                chunk=chunk_item,
                glossary=glossary_subset,
                style_hints=["qa_stage=semantic_qa", "strict_json=true"],
                style_guide=style_guide,
                chapter_notes=chapter_notes,
                translated_text=target_text,
                strict_terminology=options.strict_terminology,
                template_id="semantic_qa",
                timeout_seconds=options.timeout_seconds,
                max_attempts=options.max_attempts,
                job_id=f"qa-semantic-{_slug(chunk_id)}",
            )
            semantic_result = backend.translate_chunk(semantic_request)
            codex_semantic_jobs += 1
            _append_jsonl(
                codex_jobs_log_path,
                {
                    "stage": "qa_semantic",
                    "book_id": book_root.name,
                    "chunk_id": chunk_id,
                    "job_id": semantic_result.job.job_id,
                    "success": semantic_result.result.success,
                    "return_code": semantic_result.result.return_code,
                    "attempt_count": semantic_result.result.attempt_count,
                    "failure_reason": semantic_result.result.failure_reason or "",
                    "output_path": semantic_result.result.output_path or "",
                    "updated_at": utcnow_iso(),
                },
            )

            if semantic_result.result.success and semantic_result.output_payload is not None:
                semantic_flags = _flags_from_semantic_payload(
                    chunk_id=chunk_id,
                    payload=semantic_result.output_payload,
                )
                codex_flags_count += len(semantic_flags)
                flags.extend(semantic_flags)
            else:
                codex_failed_jobs += 1
                failure_reason = (
                    semantic_result.result.failure_reason or semantic_result.result.stderr or "semantic_qa_failed"
                )
                _append_jsonl(
                    codex_failures_log_path,
                    {
                        "stage": "qa_semantic",
                        "book_id": book_root.name,
                        "chunk_id": chunk_id,
                        "job_id": semantic_result.job.job_id,
                        "failure_reason": failure_reason,
                        "updated_at": utcnow_iso(),
                    },
                )
                codex_flags_count += 1
                flags.append(
                    _make_flag(
                        chunk_id=chunk_id,
                        severity="high",
                        message=f"Codex semantic QA failed: {failure_reason}",
                        rule_id="codex_semantic_failed",
                        source="codex_semantic",
                        details={"job_id": semantic_result.job.job_id},
                    )
                )

            terminology_request = ChunkTranslationRequest(
                workspace_root=book_root.parent,
                book_id=book_root.name,
                chunk=chunk_item,
                glossary=glossary_subset,
                style_hints=["qa_stage=terminology_check", "strict_json=true"],
                style_guide=style_guide,
                chapter_notes=chapter_notes,
                translated_text=target_text,
                strict_terminology=options.strict_terminology,
                template_id="terminology_check",
                timeout_seconds=options.timeout_seconds,
                max_attempts=options.max_attempts,
                job_id=f"qa-terminology-{_slug(chunk_id)}",
            )
            terminology_result = backend.translate_chunk(terminology_request)
            codex_terminology_jobs += 1
            _append_jsonl(
                codex_jobs_log_path,
                {
                    "stage": "qa_terminology",
                    "book_id": book_root.name,
                    "chunk_id": chunk_id,
                    "job_id": terminology_result.job.job_id,
                    "success": terminology_result.result.success,
                    "return_code": terminology_result.result.return_code,
                    "attempt_count": terminology_result.result.attempt_count,
                    "failure_reason": terminology_result.result.failure_reason or "",
                    "output_path": terminology_result.result.output_path or "",
                    "updated_at": utcnow_iso(),
                },
            )

            if terminology_result.result.success and terminology_result.output_payload is not None:
                terminology_flags = _flags_from_terminology_payload(
                    chunk_id=chunk_id,
                    payload=terminology_result.output_payload,
                )
                codex_flags_count += len(terminology_flags)
                flags.extend(terminology_flags)
            else:
                codex_failed_jobs += 1
                failure_reason = (
                    terminology_result.result.failure_reason
                    or terminology_result.result.stderr
                    or "terminology_check_failed"
                )
                _append_jsonl(
                    codex_failures_log_path,
                    {
                        "stage": "qa_terminology",
                        "book_id": book_root.name,
                        "chunk_id": chunk_id,
                        "job_id": terminology_result.job.job_id,
                        "failure_reason": failure_reason,
                        "updated_at": utcnow_iso(),
                    },
                )
                codex_flags_count += 1
                flags.append(
                    _make_flag(
                        chunk_id=chunk_id,
                        severity="high",
                        message=f"Codex terminology check failed: {failure_reason}",
                        rule_id="codex_terminology_failed",
                        source="codex_terminology",
                        details={"job_id": terminology_result.job.job_id},
                    )
                )

            codex_processed += 1
            _emit_progress_codex(
                progress_callback=progress_callback,
                processed=codex_processed,
                total=max(1, len(risky_chunks)),
                semantic_jobs=codex_semantic_jobs,
                terminology_jobs=codex_terminology_jobs,
                failures=codex_failed_jobs,
                started_at=started_at,
            )

    qa_flags_path.parent.mkdir(parents=True, exist_ok=True)
    qa_flags_path.write_text("", encoding="utf-8")
    for flag in flags:
        _append_jsonl(qa_flags_path, flag)

    counts_by_severity = Counter(str(flag.get("severity", "")) for flag in flags)
    missing_chunks = sum(1 for flag in flags if flag.get("rule_id") == "missing_translation")

    report_text = _render_qa_report(
        book_id=book_root.name,
        source_artifact=source_artifact,
        options=options,
        flags=flags,
        total_chunks=len(expected_chunk_ids),
        translated_chunks=len(translated_map),
        codex_semantic_jobs=codex_semantic_jobs,
        codex_terminology_jobs=codex_terminology_jobs,
        codex_failed_jobs=codex_failed_jobs,
    )
    qa_report_path.parent.mkdir(parents=True, exist_ok=True)
    qa_report_path.write_text(report_text, encoding="utf-8")

    elapsed = max(0.0, time.monotonic() - started_at)
    return QAResult(
        qa_flags_path=qa_flags_path,
        qa_report_path=qa_report_path,
        source_artifact=source_artifact,
        total_chunks=len(expected_chunk_ids),
        translated_chunks=len(translated_map),
        missing_chunks=missing_chunks,
        local_flags_count=local_flags_count,
        codex_flags_count=codex_flags_count,
        total_flags_count=len(flags),
        high_severity_count=int(counts_by_severity.get("high", 0)),
        medium_severity_count=int(counts_by_severity.get("medium", 0)),
        low_severity_count=int(counts_by_severity.get("low", 0)),
        codex_semantic_jobs=codex_semantic_jobs,
        codex_terminology_jobs=codex_terminology_jobs,
        codex_failed_jobs=codex_failed_jobs,
        elapsed_seconds=elapsed,
    )


def _run_local_chunk_checks(*, chunk: Chunk, translated_row: dict[str, Any]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    target_text = str(translated_row.get("target_text", ""))

    if not target_text.strip():
        flags.append(
            _make_flag(
                chunk_id=chunk.chunk_id,
                severity="high",
                message="Translated text is empty.",
                rule_id="empty_translation",
                source="local",
                details={"status": translated_row.get("status", "")},
            )
        )
        return flags

    source_markers = _source_footnote_markers(chunk)
    if source_markers:
        missing_markers = [marker for marker in source_markers if marker not in target_text]
        if missing_markers:
            flags.append(
                _make_flag(
                    chunk_id=chunk.chunk_id,
                    severity="high",
                    message="Some footnote markers are missing in translation.",
                    rule_id="footnote_marker_missing",
                    source="local",
                    details={"missing_markers": missing_markers},
                )
            )

        expected_count = len(source_markers)
        actual_count = sum(target_text.count(marker) for marker in source_markers)
        if actual_count != expected_count:
            flags.append(
                _make_flag(
                    chunk_id=chunk.chunk_id,
                    severity="medium",
                    message="Footnote markers count does not match source chunk.",
                    rule_id="footnote_count_mismatch",
                    source="local",
                    details={"expected_count": expected_count, "actual_count": actual_count},
                )
            )

    source_numbers = _extract_numbers(chunk.source_text)
    missing_numbers = [value for value in source_numbers if value not in target_text]
    if missing_numbers:
        flags.append(
            _make_flag(
                chunk_id=chunk.chunk_id,
                severity="medium",
                message="Numbers present in source were not found in translation.",
                rule_id="number_missing",
                source="local",
                details={"missing": missing_numbers[:12]},
            )
        )

    source_links = _extract_links(chunk.source_text)
    missing_links = [value for value in source_links if value not in target_text]
    if missing_links:
        flags.append(
            _make_flag(
                chunk_id=chunk.chunk_id,
                severity="high",
                message="Links present in source were lost in translation.",
                rule_id="link_missing",
                source="local",
                details={"missing": missing_links[:8]},
            )
        )

    source_dates = _extract_dates(chunk.source_text)
    missing_dates = [value for value in source_dates if not _date_supported(value, target_text)]
    if missing_dates:
        flags.append(
            _make_flag(
                chunk_id=chunk.chunk_id,
                severity="medium",
                message="Date-like values may be missing or altered in translation.",
                rule_id="date_missing",
                source="local",
                details={"missing": missing_dates[:8]},
            )
        )

    source_equations = _extract_equations(chunk.source_text)
    missing_equations = [value for value in source_equations if not _equation_supported(value, target_text)]
    if missing_equations:
        flags.append(
            _make_flag(
                chunk_id=chunk.chunk_id,
                severity="medium",
                message="Formula or equation fragments may be missing in translation.",
                rule_id="formula_content_missing",
                source="local",
                details={"missing": missing_equations[:8]},
            )
        )

    return flags


def _flags_from_semantic_payload(*, chunk_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    issues = payload.get("issues", [])
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            severity = _normalize_severity(issue.get("severity"), fallback="medium")
            message = str(issue.get("message", "semantic issue detected"))
            rule_id = str(issue.get("issue_id", "semantic_issue"))
            flags.append(
                _make_flag(
                    chunk_id=chunk_id,
                    severity=severity,
                    message=message,
                    rule_id=rule_id,
                    source="codex_semantic",
                    details={
                        "block_id": issue.get("block_id", ""),
                        "evidence": issue.get("evidence", ""),
                    },
                )
            )

    qa_passed = bool(payload.get("qa_passed", False))
    if not qa_passed and not flags:
        flags.append(
            _make_flag(
                chunk_id=chunk_id,
                severity="medium",
                message="Codex semantic QA marked chunk as failed without explicit issues.",
                rule_id="semantic_qa_failed",
                source="codex_semantic",
                details={},
            )
        )
    return flags


def _flags_from_terminology_payload(*, chunk_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    violations = payload.get("violations", [])
    if isinstance(violations, list):
        for violation in violations:
            if not isinstance(violation, dict):
                continue
            severity = _normalize_severity(violation.get("severity"), fallback="medium")
            source_term = str(violation.get("source_term", "")).strip()
            expected_target = str(violation.get("expected_target", "")).strip()
            message = str(violation.get("message", "terminology inconsistency"))
            flags.append(
                _make_flag(
                    chunk_id=chunk_id,
                    severity=severity,
                    message=message,
                    rule_id="terminology_inconsistency",
                    source="codex_terminology",
                    details={
                        "source_term": source_term,
                        "expected_target": expected_target,
                        "found_text": violation.get("found_text", ""),
                        "block_id": violation.get("block_id", ""),
                    },
                )
            )

    terminology_passed = bool(payload.get("terminology_passed", False))
    if not terminology_passed and not flags:
        flags.append(
            _make_flag(
                chunk_id=chunk_id,
                severity="medium",
                message="Codex terminology check failed without explicit violations.",
                rule_id="terminology_check_failed",
                source="codex_terminology",
                details={},
            )
        )
    return flags


def _render_qa_report(
    *,
    book_id: str,
    source_artifact: str,
    options: QAOptions,
    flags: list[dict[str, Any]],
    total_chunks: int,
    translated_chunks: int,
    codex_semantic_jobs: int,
    codex_terminology_jobs: int,
    codex_failed_jobs: int,
) -> str:
    severity_counter = Counter(str(flag.get("severity", "")) for flag in flags)
    rule_counter = Counter(str(flag.get("rule_id", "")) for flag in flags if str(flag.get("rule_id", "")).strip())

    lines: list[str] = [
        f"# QA Report: {book_id}",
        "",
        f"Generated at: {utcnow_iso()}",
        f"Source artifact: `{source_artifact}`",
        f"Codex-based QA: {'enabled' if options.codex_enabled else 'disabled'}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Expected chunks | {total_chunks} |",
        f"| Chunks with translation | {translated_chunks} |",
        f"| Total flags | {len(flags)} |",
        f"| High severity | {severity_counter.get('high', 0)} |",
        f"| Medium severity | {severity_counter.get('medium', 0)} |",
        f"| Low severity | {severity_counter.get('low', 0)} |",
        f"| Codex semantic jobs | {codex_semantic_jobs} |",
        f"| Codex terminology jobs | {codex_terminology_jobs} |",
        f"| Codex failed jobs | {codex_failed_jobs} |",
    ]

    if rule_counter:
        lines.extend(["", "## Flags By Rule", "", "| Rule | Count |", "|---|---:|"])
        for rule_id, count in sorted(rule_counter.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| `{rule_id}` | {count} |")

    high_flags = [flag for flag in flags if str(flag.get("severity", "")) == "high"]
    if high_flags:
        lines.extend(["", "## High Severity Flags", ""])
        for flag in high_flags[:50]:
            chunk_id = str(flag.get("chunk_id", ""))
            rule_id = str(flag.get("rule_id", ""))
            message = str(flag.get("message", ""))
            lines.append(f"- `{chunk_id}` `{rule_id}`: {message}")

    if not flags:
        lines.extend(["", "## Result", "", "No QA flags detected."])

    return "\n".join(lines).rstrip() + "\n"


def _select_codex_candidates(
    *,
    chunks_map: dict[str, Chunk],
    translated_map: dict[str, dict[str, Any]],
    local_flags: list[dict[str, Any]],
    codex_on_risk_only: bool,
    glossary_entries: list[GlossaryEntry],
) -> list[str]:
    available_chunk_ids = [chunk_id for chunk_id in chunks_map if chunk_id in translated_map]
    if not codex_on_risk_only:
        return available_chunk_ids

    risky: list[str] = []
    flags_by_chunk: dict[str, list[dict[str, Any]]] = {}
    for flag in local_flags:
        chunk_id = str(flag.get("chunk_id", ""))
        if not chunk_id:
            continue
        flags_by_chunk.setdefault(chunk_id, []).append(flag)

    for chunk_id in available_chunk_ids:
        chunk = chunks_map[chunk_id]
        chunk_flags = flags_by_chunk.get(chunk_id, [])
        if any(str(flag.get("severity", "")) in {"medium", "high"} for flag in chunk_flags):
            risky.append(chunk_id)
            continue

        if len(_source_footnote_markers(chunk)) >= 2:
            risky.append(chunk_id)
            continue

        if _extract_equations(chunk.source_text):
            risky.append(chunk_id)
            continue

        if len(chunk.source_text) >= 1200:
            risky.append(chunk_id)
            continue

        glossary_subset = _build_glossary_subset(chunk.source_text, glossary_entries)
        if len(glossary_subset) >= 4:
            risky.append(chunk_id)

    return risky


def _build_glossary_subset(source_text: str, entries: list[GlossaryEntry]) -> list[dict[str, str]]:
    if not source_text.strip() or not entries:
        return []
    exact, fuzzy = slice_glossary_entries(
        source_text,
        entries,
        max_exact=12,
        max_fuzzy=6,
    )

    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in [*exact, *fuzzy]:
        source = entry.source_term.strip()
        target = entry.target_term.strip()
        if not source or not target:
            continue
        key = source.lower()
        if key in seen:
            continue
        seen.add(key)
        selected.append({"source": source, "target": target, "note": entry.notes})
    return selected


def _load_completed_translation_map(
    *, translated_path: Path, edited_path: Path
) -> tuple[dict[str, dict[str, Any]], str]:
    translated_rows = _load_jsonl(translated_path)
    edited_rows = _load_jsonl(edited_path)

    result: dict[str, dict[str, Any]] = {}
    for row in translated_rows:
        chunk_id = str(row.get("chunk_id", ""))
        status = str(row.get("status", ""))
        if not chunk_id or status != "completed":
            continue
        copy = dict(row)
        copy["_source_artifact"] = "translated_chunks.jsonl"
        result[chunk_id] = copy

    for row in edited_rows:
        chunk_id = str(row.get("chunk_id", ""))
        status = str(row.get("status", ""))
        if not chunk_id or status != "completed":
            continue
        copy = dict(row)
        copy["_source_artifact"] = "edited_chunks.jsonl"
        result[chunk_id] = copy

    source_artifact = (
        "edited_chunks.jsonl + fallback translated_chunks.jsonl" if edited_rows else "translated_chunks.jsonl"
    )
    return result, source_artifact


def _load_chunks_map(path: Path) -> dict[str, Chunk]:
    mapping: dict[str, Chunk] = {}
    for row in _load_jsonl(path):
        if "chunk_id" not in row:
            continue
        chunk = Chunk.from_dict(row)
        mapping[chunk.chunk_id] = chunk
    return mapping


def _source_footnote_markers(chunk: Chunk) -> list[str]:
    markers: list[str] = []
    seen: set[str] = set()
    for item in chunk.footnote_refs:
        if not isinstance(item, dict):
            continue
        marker_raw = item.get("marker")
        if marker_raw is None:
            marker_raw = item.get("id")
        if marker_raw is None:
            continue
        marker = str(marker_raw).strip()
        if not marker:
            continue
        if marker in seen:
            continue
        seen.add(marker)
        markers.append(marker)
    return markers


def _extract_numbers(text: str) -> list[str]:
    values = {match.group(0) for match in _NUMBER_RE.finditer(text)}
    return sorted(values)


def _extract_links(text: str) -> list[str]:
    values = {match.group(0) for match in _URL_RE.finditer(text)}
    return sorted(values)


def _extract_dates(text: str) -> list[str]:
    dates: set[str] = set()
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            dates.add(match.group(0))
    return sorted(dates)


def _extract_equations(text: str) -> list[str]:
    equations = {_normalize_equation(match.group(0)) for match in _EQUATION_RE.finditer(text)}
    equations.discard("")
    return sorted(equations)


def _date_supported(source_date: str, target_text: str) -> bool:
    if source_date in target_text:
        return True
    digits = re.findall(r"\d+", source_date)
    if not digits:
        return True
    return all(token in target_text for token in digits)


def _equation_supported(source_equation: str, target_text: str) -> bool:
    if source_equation in target_text:
        return True

    compact_target = _normalize_equation(target_text)
    if source_equation and source_equation in compact_target:
        return True

    if "=" not in source_equation or "=" not in target_text:
        return False

    left_side = source_equation.split("=", 1)[0].strip()
    if left_side and left_side in target_text:
        return True

    numeric_tokens = re.findall(r"\d+(?:[.,]\d+)?", source_equation)
    if numeric_tokens and all(token in target_text for token in numeric_tokens):
        return True

    return False


def _normalize_equation(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    return compact.strip()


def _normalize_severity(value: object, *, fallback: Severity) -> Severity:
    text = str(value).strip().lower()
    if text in {"low", "medium", "high"}:
        return text  # type: ignore[return-value]
    return fallback


def _make_flag(
    *,
    chunk_id: str,
    severity: Severity,
    message: str,
    rule_id: str,
    source: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    base = QAFlag(
        chunk_id=chunk_id,
        severity=severity,
        message=message,
        rule_id=rule_id,
    ).to_dict()
    base["type"] = rule_id
    base["source"] = source
    base["details"] = details
    base["updated_at"] = utcnow_iso()
    return base


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


def _emit_progress_local(
    *,
    progress_callback: ProgressCallback | None,
    processed: int,
    total: int,
    flags_count: int,
    started_at: float,
) -> None:
    if progress_callback is None:
        return

    elapsed = max(0.0, time.monotonic() - started_at)
    eta_seconds = 0.0
    if processed > 0 and total > processed:
        eta_seconds = (elapsed / processed) * (total - processed)

    progress_callback(
        f"QA local {processed}/{total} | flags={flags_count} "
        f"| elapsed={_format_duration(elapsed)} eta={_format_duration(eta_seconds)}"
    )


def _emit_progress_codex(
    *,
    progress_callback: ProgressCallback | None,
    processed: int,
    total: int,
    semantic_jobs: int,
    terminology_jobs: int,
    failures: int,
    started_at: float,
) -> None:
    if progress_callback is None:
        return

    elapsed = max(0.0, time.monotonic() - started_at)
    eta_seconds = 0.0
    if processed > 0 and total > processed:
        eta_seconds = (elapsed / processed) * (total - processed)

    progress_callback(
        f"QA codex {processed}/{total} | semantic_jobs={semantic_jobs} "
        f"terminology_jobs={terminology_jobs} failures={failures} "
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


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    if not slug:
        return "chunk"
    return slug
