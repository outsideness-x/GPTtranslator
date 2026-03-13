"""Economy orchestration services used by CLI commands."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ...core.manifest import load_book_manifest
from ...core.models import BookManifest, Chunk
from ...memory.glossary_manager import GlossaryEntry, parse_glossary_entries
from ...memory.translation_memory_manager import TranslationMemoryEntry, load_translation_memory
from .adaptive import adapt_chunks
from .budget import BudgetEstimate, BudgetEstimatorOptions, estimate_budget
from .dedupe import load_job_cache
from .planner import ChunkPlan, EconomyRunSummary, PlannerOptions, plan_chunks
from .profiles import EconomyProfile, ProfileName, choose_default_profile, get_profile


class EconomyDataError(RuntimeError):
    """Raised when economy planner prerequisites are missing."""


@dataclass(frozen=True, slots=True)
class EconomyBookData:
    """Loaded book data needed for cost-aware planning and budget estimation."""

    book_id: str
    book_root: Path
    manifest: BookManifest
    chunks: list[Chunk]
    page_count: int
    glossary_entries: list[GlossaryEntry]
    glossary_issues: list[str]
    tm_entries: list[TranslationMemoryEntry]
    tm_issues: list[str]
    style_guide_text: str
    chapter_notes_text: str


@dataclass(frozen=True, slots=True)
class EconomyPlanRequest:
    """Options shared by translate/budget economy commands."""

    profile: ProfileName | None = None
    max_context_entries: int | None = None
    tm_first: bool = True
    no_editorial: bool = False
    qa_on_risk_only: bool | None = None
    reuse_cache: bool = True
    max_retries: int | None = None
    adaptive_chunking: bool = True
    is_test_run: bool = False


@dataclass(frozen=True, slots=True)
class EconomyPlanResult:
    """Materialized planning artifacts and summary metrics."""

    selected_profile: EconomyProfile
    chunks_before: int
    chunks_after: int
    plans: list[ChunkPlan]
    summary: EconomyRunSummary
    cache_entries: int
    plan_path: Path
    summary_path: Path
    cache_path: Path


@dataclass(frozen=True, slots=True)
class BudgetReport:
    """Budget estimate with selected profile context."""

    selected_profile: EconomyProfile
    estimate: BudgetEstimate


def load_book_economy_data(
    *,
    project_root: Path,
    workspace_dir_name: str,
    book_id: str,
) -> EconomyBookData:
    """Load chunks + memory assets for economy planning."""

    book_root = (project_root / workspace_dir_name / book_id).resolve()
    manifest_path = book_root / "manifest.json"
    if not manifest_path.exists():
        raise EconomyDataError(f"manifest not found: {manifest_path}")

    manifest = load_book_manifest(manifest_path)
    chunks_path = book_root / "analysis" / "chunks.jsonl"
    chunks = _load_chunks_jsonl(chunks_path) if chunks_path.exists() else list(manifest.chunks)
    if not chunks:
        chunks = list(manifest.chunks)

    if not chunks:
        raise EconomyDataError("no chunks found; run `gpttranslator extract <book_id>` first")

    memory_dir = book_root / "memory"
    glossary_path = memory_dir / "glossary.md"
    tm_path = memory_dir / "translation_memory.jsonl"
    style_guide_path = memory_dir / "style_guide.md"
    chapter_notes_path = memory_dir / "chapter_notes.md"

    glossary_entries, glossary_issues = parse_glossary_entries(glossary_path)
    tm_entries, tm_issues = load_translation_memory(tm_path)

    style_guide_text = _safe_read_text(style_guide_path)
    chapter_notes_text = _safe_read_text(chapter_notes_path)
    page_count = _resolve_page_count(manifest, chunks)

    return EconomyBookData(
        book_id=book_id,
        book_root=book_root,
        manifest=manifest,
        chunks=chunks,
        page_count=page_count,
        glossary_entries=glossary_entries,
        glossary_issues=glossary_issues,
        tm_entries=tm_entries,
        tm_issues=tm_issues,
        style_guide_text=style_guide_text,
        chapter_notes_text=chapter_notes_text,
    )


def build_economy_plan(
    *,
    data: EconomyBookData,
    request: EconomyPlanRequest,
) -> EconomyPlanResult:
    """Run adaptive chunking + tier routing + context minimization planner."""

    profile = _select_profile(data=data, request=request)
    effective_context_entries = _resolve_positive_int(request.max_context_entries, profile.max_context_entries)
    effective_max_retries = _resolve_positive_int(request.max_retries, profile.max_retries)
    qa_on_risk_only = profile.qa_on_risk_only if request.qa_on_risk_only is None else request.qa_on_risk_only

    chunks_before = len(data.chunks)
    planned_chunks = adapt_chunks(data.chunks, profile=profile, enabled=request.adaptive_chunking)
    chunks_after = len(planned_chunks)

    cache_path = data.book_root / "translated" / "job_cache.json"
    job_cache = load_job_cache(cache_path) if request.reuse_cache else {}
    planner_job_cache = cast(dict[str, object], job_cache)

    plans, summary = plan_chunks(
        chunks=planned_chunks,
        glossary_entries=data.glossary_entries,
        tm_entries=data.tm_entries,
        style_guide_text=data.style_guide_text,
        chapter_notes_text=data.chapter_notes_text,
        profile=profile,
        options=PlannerOptions(
            max_context_entries=effective_context_entries,
            tm_first=request.tm_first,
            no_editorial=request.no_editorial,
            qa_on_risk_only=qa_on_risk_only,
            reuse_cache=request.reuse_cache,
            max_retries=effective_max_retries,
        ),
        job_cache=planner_job_cache,
    )

    plan_path = data.book_root / "translated" / "economy_plan.json"
    summary_path = data.book_root / "logs" / "economy_summary.json"
    _write_json(plan_path, _serialize_plan_payload(data=data, profile=profile, request=request, plans=plans))
    _write_json(
        summary_path,
        _serialize_summary_payload(
            data=data,
            profile=profile,
            request=request,
            summary=summary,
            chunks_before=chunks_before,
            chunks_after=chunks_after,
        ),
    )

    return EconomyPlanResult(
        selected_profile=profile,
        chunks_before=chunks_before,
        chunks_after=chunks_after,
        plans=plans,
        summary=summary,
        cache_entries=len(job_cache),
        plan_path=plan_path,
        summary_path=summary_path,
        cache_path=cache_path,
    )


def estimate_book_budget(
    *,
    data: EconomyBookData,
    request: EconomyPlanRequest,
) -> BudgetReport:
    """Return heuristic budget estimate for current run settings."""

    profile = _select_profile(data=data, request=request)
    effective_context_entries = _resolve_positive_int(request.max_context_entries, profile.max_context_entries)
    qa_on_risk_only = profile.qa_on_risk_only if request.qa_on_risk_only is None else request.qa_on_risk_only
    chunks = adapt_chunks(data.chunks, profile=profile, enabled=request.adaptive_chunking)

    estimate = estimate_budget(
        chunks=chunks,
        tm_entries=data.tm_entries,
        profile=profile,
        page_count=data.page_count,
        options=BudgetEstimatorOptions(
            tm_first=request.tm_first,
            no_editorial=request.no_editorial,
            qa_on_risk_only=qa_on_risk_only,
            no_codex_qa=not profile.enable_codex_qa,
            max_context_entries=effective_context_entries,
        ),
    )
    return BudgetReport(selected_profile=profile, estimate=estimate)


def write_budget_report(
    *,
    data: EconomyBookData,
    report: BudgetReport,
    request: EconomyPlanRequest,
) -> Path:
    """Persist budget estimation report for resume and auditability."""

    path = data.book_root / "logs" / "budget_estimate.json"
    payload = {
        "book_id": data.book_id,
        "page_count": data.page_count,
        "profile": report.selected_profile.name,
        "request": {
            "tm_first": request.tm_first,
            "no_editorial": request.no_editorial,
            "qa_on_risk_only": request.qa_on_risk_only,
            "adaptive_chunking": request.adaptive_chunking,
            "max_context_entries": request.max_context_entries,
            "max_retries": request.max_retries,
        },
        "estimate": {
            "estimated_chunk_count": report.estimate.estimated_chunk_count,
            "estimated_codex_job_count": report.estimate.estimated_codex_job_count,
            "estimated_heavy_job_count": report.estimate.estimated_heavy_job_count,
            "estimated_retries_risk": report.estimate.estimated_retries_risk,
            "estimated_editorial_job_count": report.estimate.estimated_editorial_job_count,
            "estimated_qa_job_count": report.estimate.estimated_qa_job_count,
            "estimated_local_reuse_count": report.estimate.estimated_local_reuse_count,
            "average_chunk_chars": report.estimate.average_chunk_chars,
            "expected_context_weight": report.estimate.expected_context_weight,
            "session_pressure": report.estimate.session_pressure,
            "recommended_profile": report.estimate.recommended_profile,
            "warnings": list(report.estimate.warnings),
        },
    }
    _write_json(path, payload)
    return path


def _select_profile(*, data: EconomyBookData, request: EconomyPlanRequest) -> EconomyProfile:
    profile_name: ProfileName
    if request.profile is None:
        profile_name = choose_default_profile(data.page_count, is_test_run=request.is_test_run)
    else:
        profile_name = request.profile
    return get_profile(profile_name)


def _resolve_page_count(manifest: BookManifest, chunks: list[Chunk]) -> int:
    extraction_meta = manifest.metadata.get("extraction", {})
    if isinstance(extraction_meta, dict):
        page_count = extraction_meta.get("page_count")
        if isinstance(page_count, int) and page_count > 0:
            return page_count

    if manifest.pages:
        return max(page.page_num for page in manifest.pages)

    if chunks:
        return max(chunk.page_range[1] for chunk in chunks)

    return 0


def _resolve_positive_int(value: int | None, fallback: int) -> int:
    if value is None:
        return fallback
    return max(1, int(value))


def _load_chunks_jsonl(path: Path) -> list[Chunk]:
    if not path.exists():
        return []

    chunks: list[Chunk] = []
    for index, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EconomyDataError(f"invalid chunks.jsonl at line {index}: {exc.msg}") from exc
        if isinstance(payload, dict):
            chunks.append(Chunk.from_dict(payload))
    return chunks


def _safe_read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _serialize_plan_payload(
    *,
    data: EconomyBookData,
    profile: EconomyProfile,
    request: EconomyPlanRequest,
    plans: list[ChunkPlan],
) -> dict[str, Any]:
    tier_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    plan_items: list[dict[str, Any]] = []
    for plan in plans:
        tier_counts[plan.tier] = tier_counts.get(plan.tier, 0) + 1
        plan_items.append(
            {
                "chunk_id": plan.chunk.chunk_id,
                "chapter_id": plan.chunk.chapter_id,
                "action": plan.action,
                "reason": plan.reason,
                "tier": plan.tier,
                "complexity_score": round(plan.complexity.score, 4),
                "risk_flags": list(plan.complexity.risk_flags),
                "template_id": plan.template_id,
                "run_editorial": plan.run_editorial,
                "run_semantic_qa": plan.run_semantic_qa,
                "context_weight": plan.context_package.context_weight if plan.context_package else 0,
                "fingerprint": plan.fingerprint,
                "cache_hit_output": str(plan.cache_hit_output) if plan.cache_hit_output is not None else None,
                "prefilter_reason": plan.prefilter.reason,
            }
        )

    return {
        "book_id": data.book_id,
        "page_count": data.page_count,
        "profile": profile.name,
        "request": {
            "tm_first": request.tm_first,
            "no_editorial": request.no_editorial,
            "qa_on_risk_only": request.qa_on_risk_only,
            "reuse_cache": request.reuse_cache,
            "max_context_entries": request.max_context_entries,
            "max_retries": request.max_retries,
            "adaptive_chunking": request.adaptive_chunking,
        },
        "tier_counts": tier_counts,
        "plans": plan_items,
    }


def _serialize_summary_payload(
    *,
    data: EconomyBookData,
    profile: EconomyProfile,
    request: EconomyPlanRequest,
    summary: EconomyRunSummary,
    chunks_before: int,
    chunks_after: int,
) -> dict[str, Any]:
    return {
        "book_id": data.book_id,
        "page_count": data.page_count,
        "profile": profile.name,
        "chunks_before": chunks_before,
        "chunks_after": chunks_after,
        "tm_first": request.tm_first,
        "reuse_cache": request.reuse_cache,
        "no_editorial": request.no_editorial,
        "qa_on_risk_only": request.qa_on_risk_only,
        "adaptive_chunking": request.adaptive_chunking,
        "metrics": {
            "chunk_count": summary.chunk_count,
            "codex_chunks": summary.codex_chunks,
            "tm_reuse_chunks": summary.tm_reuse_chunks,
            "repeated_reuse_chunks": summary.repeated_reuse_chunks,
            "cache_hits": summary.cache_hits,
            "skipped_chunks": summary.skipped_chunks,
            "editorial_jobs": summary.editorial_jobs,
            "qa_jobs": summary.qa_jobs,
            "editorial_skipped": summary.editorial_skipped,
            "qa_skipped": summary.qa_skipped,
            "retries_avoided": summary.retries_avoided,
            "avg_context_weight": summary.avg_context_weight,
            "estimated_savings_percent": summary.estimated_savings_percent(),
        },
    }
