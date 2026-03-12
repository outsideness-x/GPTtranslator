"""Cost-aware translation planner orchestrating economy logic layers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ...core.models import Chunk
from ...memory.glossary_manager import GlossaryEntry
from ...memory.translation_memory_manager import TranslationMemoryEntry
from .complexity import ComplexityAssessment, assess_chunk_complexity, route_chunk_tier
from .context import ContextBuildSettings, ContextPackage, build_context_package
from .dedupe import build_content_fingerprint, find_cache_hit
from .prefilter import PreFilterDecision, PreFilterSettings, decide_prefilter_action
from .profiles import EconomyProfile
from .tm import normalize_text

PlanAction = Literal["skip", "reuse_tm", "reuse_repeat", "reuse_cache", "codex"]


@dataclass(frozen=True, slots=True)
class PlannerOptions:
    """Runtime options that adjust economy planner behavior."""

    max_context_entries: int
    tm_first: bool
    no_editorial: bool
    qa_on_risk_only: bool
    reuse_cache: bool
    max_retries: int


@dataclass(slots=True)
class ChunkPlan:
    """Per-chunk routing decision with economy metadata."""

    chunk: Chunk
    action: PlanAction
    reason: str
    tier: str
    complexity: ComplexityAssessment
    template_id: str
    context_package: ContextPackage | None
    fingerprint: str | None
    run_editorial: bool
    run_semantic_qa: bool
    cache_hit_output: Path | None
    prefilter: PreFilterDecision


@dataclass(slots=True)
class EconomyRunSummary:
    """Aggregate savings metrics for translation run observability."""

    profile_name: str
    chunk_count: int
    codex_chunks: int = 0
    tm_reuse_chunks: int = 0
    repeated_reuse_chunks: int = 0
    cache_hits: int = 0
    skipped_chunks: int = 0
    editorial_jobs: int = 0
    qa_jobs: int = 0
    editorial_skipped: int = 0
    qa_skipped: int = 0
    retries_avoided: int = 0
    avg_context_weight: float = 0.0

    def estimated_savings_percent(self) -> float:
        baseline_jobs = self.chunk_count * 3
        actual_jobs = self.codex_chunks + self.editorial_jobs + self.qa_jobs
        if baseline_jobs <= 0:
            return 0.0
        saved = max(0, baseline_jobs - actual_jobs)
        return round((saved / baseline_jobs) * 100.0, 1)


def plan_chunks(
    *,
    chunks: list[Chunk],
    glossary_entries: list[GlossaryEntry],
    tm_entries: list[TranslationMemoryEntry],
    style_guide_text: str,
    chapter_notes_text: str,
    profile: EconomyProfile,
    options: PlannerOptions,
    job_cache: dict[str, object] | None = None,
) -> tuple[list[ChunkPlan], EconomyRunSummary]:
    """Plan chunk routing and selective Codex passes for economy mode."""

    plans: list[ChunkPlan] = []
    summary = EconomyRunSummary(profile_name=profile.name, chunk_count=len(chunks))

    prefilter_settings = PreFilterSettings(
        tm_first=options.tm_first,
        exact_threshold=profile.tm_exact_threshold,
        near_threshold=profile.tm_near_threshold,
        allow_near_reuse=profile.name == "economy",
    )

    repeated_reuse_map: dict[str, str] = {}
    context_weight_sum = 0
    context_weight_count = 0

    for chunk in chunks:
        complexity = assess_chunk_complexity(chunk)
        tier = route_chunk_tier(
            complexity,
            tier_b_threshold=profile.tier_b_threshold,
            tier_c_threshold=profile.tier_c_threshold,
        )

        prefilter = decide_prefilter_action(
            chunk,
            tm_entries=tm_entries,
            repeated_translations=repeated_reuse_map,
            settings=prefilter_settings,
        )

        if prefilter.action == "skip":
            summary.skipped_chunks += 1
            plans.append(
                ChunkPlan(
                    chunk=chunk,
                    action="skip",
                    reason=prefilter.reason,
                    tier=tier,
                    complexity=complexity,
                    template_id="translate_chunk",
                    context_package=None,
                    fingerprint=None,
                    run_editorial=False,
                    run_semantic_qa=False,
                    cache_hit_output=None,
                    prefilter=prefilter,
                )
            )
            continue

        if prefilter.action == "reuse":
            if prefilter.reason.startswith("translation_memory"):
                summary.tm_reuse_chunks += 1
                action: PlanAction = "reuse_tm"
            else:
                summary.repeated_reuse_chunks += 1
                action = "reuse_repeat"

            if prefilter.target_text:
                repeated_reuse_map[normalize_text(chunk.source_text)] = prefilter.target_text

            plans.append(
                ChunkPlan(
                    chunk=chunk,
                    action=action,
                    reason=prefilter.reason,
                    tier=tier,
                    complexity=complexity,
                    template_id="translate_chunk",
                    context_package=None,
                    fingerprint=None,
                    run_editorial=False,
                    run_semantic_qa=False,
                    cache_hit_output=None,
                    prefilter=prefilter,
                )
            )
            continue

        context_package = build_context_package(
            chunk,
            glossary_entries=glossary_entries,
            tm_entries=tm_entries,
            style_guide_text=style_guide_text,
            chapter_notes_text=chapter_notes_text,
            settings=ContextBuildSettings(
                max_context_entries=max(1, options.max_context_entries),
                max_glossary_exact=min(profile.max_glossary_entries, max(4, options.max_context_entries)),
                max_glossary_fuzzy=max(2, min(8, options.max_context_entries // 2)),
                max_tm_matches=min(profile.max_tm_matches, max(1, options.max_context_entries // 2)),
                max_style_rules=max(3, min(10, options.max_context_entries)),
                chapter_notes_char_limit=max(220, profile.context_chars * 3),
            ),
            tm_exact_threshold=profile.tm_exact_threshold,
            tm_near_threshold=profile.tm_near_threshold,
        )
        context_weight_sum += context_package.context_weight
        context_weight_count += 1

        fingerprint = build_content_fingerprint(
            chunk=chunk,
            context_package=context_package,
            profile_name=profile.name,
            template_id="translate_chunk",
            template_version=1,
        )

        cache_hit_output: Path | None = None
        if options.reuse_cache and isinstance(job_cache, dict):
            from .dedupe import JobCacheRecord

            typed_cache = {
                key: value
                for key, value in job_cache.items()
                if isinstance(value, JobCacheRecord)
            }
            cache_hit_output = find_cache_hit(
                cache=typed_cache,
                fingerprint=fingerprint,
                expected_job_id=None,
                expected_template_id="translate_chunk",
            )

        if cache_hit_output is not None:
            summary.cache_hits += 1
            plans.append(
                ChunkPlan(
                    chunk=chunk,
                    action="reuse_cache",
                    reason="job_cache_hit",
                    tier=tier,
                    complexity=complexity,
                    template_id="translate_chunk",
                    context_package=context_package,
                    fingerprint=fingerprint,
                    run_editorial=False,
                    run_semantic_qa=False,
                    cache_hit_output=cache_hit_output,
                    prefilter=prefilter,
                )
            )
            continue

        summary.codex_chunks += 1
        run_editorial = _should_run_editorial(
            tier=tier,
            complexity=complexity,
            context_package=context_package,
            profile=profile,
            options=options,
        )
        run_semantic_qa = _should_run_semantic_qa(
            tier=tier,
            complexity=complexity,
            profile=profile,
            options=options,
        )

        if run_editorial:
            summary.editorial_jobs += 1
        else:
            summary.editorial_skipped += 1

        if run_semantic_qa:
            summary.qa_jobs += 1
        else:
            summary.qa_skipped += 1

        plans.append(
            ChunkPlan(
                chunk=chunk,
                action="codex",
                reason="tier_routed",
                tier=tier,
                complexity=complexity,
                template_id="translate_chunk",
                context_package=context_package,
                fingerprint=fingerprint,
                run_editorial=run_editorial,
                run_semantic_qa=run_semantic_qa,
                cache_hit_output=None,
                prefilter=prefilter,
            )
        )

    if context_weight_count:
        summary.avg_context_weight = round(context_weight_sum / context_weight_count, 1)

    baseline_retries = 3
    summary.retries_avoided = summary.codex_chunks * max(0, baseline_retries - options.max_retries)

    return plans, summary


def _should_run_editorial(
    *,
    tier: str,
    complexity: ComplexityAssessment,
    context_package: ContextPackage,
    profile: EconomyProfile,
    options: PlannerOptions,
) -> bool:
    if options.no_editorial or not profile.enable_editorial:
        return False

    if tier == "C":
        return True

    if "terminology_dense" in complexity.risk_flags:
        return True

    if context_package.fuzzy_glossary:
        return True

    if context_package.chapter_term_decisions and tier == "B":
        return True

    return False


def _should_run_semantic_qa(
    *,
    tier: str,
    complexity: ComplexityAssessment,
    profile: EconomyProfile,
    options: PlannerOptions,
) -> bool:
    if not profile.enable_codex_qa:
        return False

    if options.qa_on_risk_only:
        return (
            tier == "C"
            or "footnote_markers" in complexity.risk_flags
            or "terminology_dense" in complexity.risk_flags
            or "numeric_or_formula_dense" in complexity.risk_flags
        )

    return tier in {"B", "C"}
