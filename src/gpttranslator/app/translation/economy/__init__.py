"""Cost-aware translation pipeline utilities."""

from .adaptive import adapt_chunks
from .budget import BudgetEstimate, BudgetEstimatorOptions, estimate_budget
from .complexity import ChunkTier, ComplexityAssessment, ComplexityFeatures, assess_chunk_complexity, route_chunk_tier
from .context import ContextBuildSettings, ContextPackage, build_context_package, slice_glossary_entries
from .dedupe import (
    JobCacheRecord,
    build_content_fingerprint,
    find_cache_hit,
    load_job_cache,
    save_job_cache,
    update_cache_record,
)
from .planner import ChunkPlan, EconomyRunSummary, PlannerOptions, plan_chunks
from .prefilter import PreFilterDecision, PreFilterSettings, decide_prefilter_action
from .profiles import EconomyProfile, ProfileName, choose_default_profile, get_profile
from .retry import RetryDirective, decide_retry_directive
from .service import (
    BudgetReport,
    EconomyBookData,
    EconomyDataError,
    EconomyPlanRequest,
    EconomyPlanResult,
    build_economy_plan,
    estimate_book_budget,
    load_book_economy_data,
    write_budget_report,
)
from .tm import TMMatchedEntry, find_exact_tm_match, find_tm_matches, normalize_text, similarity_ratio

__all__ = [
    "adapt_chunks",
    "BudgetEstimate",
    "BudgetEstimatorOptions",
    "estimate_budget",
    "ChunkTier",
    "ComplexityAssessment",
    "ComplexityFeatures",
    "assess_chunk_complexity",
    "route_chunk_tier",
    "ContextBuildSettings",
    "ContextPackage",
    "build_context_package",
    "slice_glossary_entries",
    "JobCacheRecord",
    "build_content_fingerprint",
    "find_cache_hit",
    "load_job_cache",
    "save_job_cache",
    "update_cache_record",
    "ChunkPlan",
    "EconomyRunSummary",
    "PlannerOptions",
    "plan_chunks",
    "PreFilterDecision",
    "PreFilterSettings",
    "decide_prefilter_action",
    "EconomyProfile",
    "ProfileName",
    "choose_default_profile",
    "get_profile",
    "RetryDirective",
    "decide_retry_directive",
    "BudgetReport",
    "EconomyBookData",
    "EconomyDataError",
    "EconomyPlanRequest",
    "EconomyPlanResult",
    "build_economy_plan",
    "estimate_book_budget",
    "load_book_economy_data",
    "write_budget_report",
    "TMMatchedEntry",
    "find_exact_tm_match",
    "find_tm_matches",
    "normalize_text",
    "similarity_ratio",
]
