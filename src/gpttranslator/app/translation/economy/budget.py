"""Heuristic budget estimator for codex-usage planning."""

from __future__ import annotations

from dataclasses import dataclass

from ...core.models import Chunk
from ...memory.translation_memory_manager import TranslationMemoryEntry
from .complexity import assess_chunk_complexity, route_chunk_tier
from .prefilter import PreFilterSettings, decide_prefilter_action
from .profiles import EconomyProfile, ProfileName
from .tm import normalize_text


@dataclass(frozen=True, slots=True)
class BudgetEstimatorOptions:
    """Planner options affecting expected Codex pressure."""

    tm_first: bool = True
    no_editorial: bool = False
    qa_on_risk_only: bool = True
    no_codex_qa: bool = False
    max_context_entries: int = 12


@dataclass(frozen=True, slots=True)
class BudgetEstimate:
    """Heuristic estimate for long-book translation run."""

    estimated_chunk_count: int
    estimated_codex_job_count: int
    estimated_heavy_job_count: int
    estimated_retries_risk: str
    estimated_editorial_job_count: int
    estimated_qa_job_count: int
    estimated_local_reuse_count: int
    average_chunk_chars: float
    expected_context_weight: int
    session_pressure: str
    recommended_profile: ProfileName
    warnings: tuple[str, ...]


def estimate_budget(
    *,
    chunks: list[Chunk],
    tm_entries: list[TranslationMemoryEntry],
    profile: EconomyProfile,
    page_count: int,
    options: BudgetEstimatorOptions,
) -> BudgetEstimate:
    """Estimate codex job pressure without external token APIs."""

    if not chunks:
        return BudgetEstimate(
            estimated_chunk_count=0,
            estimated_codex_job_count=0,
            estimated_heavy_job_count=0,
            estimated_retries_risk="low",
            estimated_editorial_job_count=0,
            estimated_qa_job_count=0,
            estimated_local_reuse_count=0,
            average_chunk_chars=0.0,
            expected_context_weight=0,
            session_pressure="low",
            recommended_profile="balanced",
            warnings=("No chunks detected. Run extract first.",),
        )

    prefilter_settings = PreFilterSettings(
        tm_first=options.tm_first,
        exact_threshold=profile.tm_exact_threshold,
        near_threshold=profile.tm_near_threshold,
        allow_near_reuse=profile.name == "economy",
    )

    repeated: dict[str, str] = {}
    codex_jobs = 0
    heavy_jobs = 0
    editorial_jobs = 0
    qa_jobs = 0
    local_reuse = 0
    total_chars = 0
    high_risk_chunks = 0

    for chunk in chunks:
        total_chars += len(chunk.source_text)
        assessment = assess_chunk_complexity(chunk)
        tier = route_chunk_tier(
            assessment,
            tier_b_threshold=profile.tier_b_threshold,
            tier_c_threshold=profile.tier_c_threshold,
        )

        prefilter = decide_prefilter_action(
            chunk,
            tm_entries=tm_entries,
            repeated_translations=repeated,
            settings=prefilter_settings,
        )

        if prefilter.action != "codex":
            local_reuse += 1
            if prefilter.target_text:
                repeated[normalize_text(chunk.source_text)] = prefilter.target_text
            continue

        codex_jobs += 1
        is_high_risk = (
            tier == "C" or "terminology_dense" in assessment.risk_flags or "footnote_markers" in assessment.risk_flags
        )
        if is_high_risk:
            high_risk_chunks += 1

        if profile.enable_editorial and not options.no_editorial:
            needs_editorial = tier == "C" or (tier == "B" and is_high_risk)
            if needs_editorial:
                editorial_jobs += 1

        if profile.enable_codex_qa and not options.no_codex_qa:
            if options.qa_on_risk_only:
                needs_qa = is_high_risk
            else:
                needs_qa = tier in {"B", "C"}
            if needs_qa:
                qa_jobs += 1

        if tier == "C":
            heavy_jobs += 1

    estimated_codex_jobs = codex_jobs + editorial_jobs + qa_jobs

    avg_chars = total_chars / max(1, len(chunks))
    context_weight = int(avg_chars * 0.22 + options.max_context_entries * 35 + profile.max_glossary_entries * 14)

    pressure_score = estimated_codex_jobs + heavy_jobs * 1.7 + (page_count / 55)
    if pressure_score >= 220:
        session_pressure = "high"
    elif pressure_score >= 110:
        session_pressure = "medium"
    else:
        session_pressure = "low"

    retries_risk = _estimate_retry_risk(
        high_risk_chunks=high_risk_chunks,
        total_chunks=len(chunks),
        profile=profile,
    )

    recommended = _recommend_profile(
        page_count=page_count,
        session_pressure=session_pressure,
        heavy_ratio=heavy_jobs / max(1, len(chunks)),
    )

    warnings: list[str] = []
    if page_count >= 300 and session_pressure != "low":
        warnings.append("Book is large. Split translation by chapter batches for safer 5-hour usage windows.")
    if heavy_jobs >= max(12, len(chunks) // 3):
        warnings.append("High share of heavy chunks detected. Enable adaptive chunking and risk-only QA.")
    if estimated_codex_jobs >= max(180, len(chunks) * 2):
        warnings.append("Estimated Codex call pressure is high for one pass.")

    return BudgetEstimate(
        estimated_chunk_count=len(chunks),
        estimated_codex_job_count=estimated_codex_jobs,
        estimated_heavy_job_count=heavy_jobs,
        estimated_retries_risk=retries_risk,
        estimated_editorial_job_count=editorial_jobs,
        estimated_qa_job_count=qa_jobs,
        estimated_local_reuse_count=local_reuse,
        average_chunk_chars=round(avg_chars, 1),
        expected_context_weight=context_weight,
        session_pressure=session_pressure,
        recommended_profile=recommended,
        warnings=tuple(warnings),
    )


def _estimate_retry_risk(*, high_risk_chunks: int, total_chunks: int, profile: EconomyProfile) -> str:
    ratio = high_risk_chunks / max(1, total_chunks)
    adjusted = ratio * (1.1 if profile.max_retries >= 3 else 0.9)
    if adjusted >= 0.35:
        return "high"
    if adjusted >= 0.16:
        return "medium"
    return "low"


def _recommend_profile(*, page_count: int, session_pressure: str, heavy_ratio: float) -> ProfileName:
    if page_count >= 450 or session_pressure == "high":
        return "economy"
    if heavy_ratio >= 0.28 and page_count <= 180:
        return "quality"
    return "balanced"
