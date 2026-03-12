"""Cost-aware execution profiles for translation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProfileName = Literal["economy", "balanced", "quality"]


@dataclass(frozen=True, slots=True)
class EconomyProfile:
    """Runtime profile controlling codex usage pressure and quality tradeoffs."""

    name: ProfileName
    chunk_max_chars: int
    chunk_max_blocks: int
    context_chars: int
    max_context_entries: int
    max_glossary_entries: int
    max_tm_matches: int
    tm_exact_threshold: float
    tm_near_threshold: float
    enable_editorial: bool
    enable_codex_qa: bool
    qa_on_risk_only: bool
    max_retries: int
    strict_retry_mode: bool
    tier_b_threshold: float
    tier_c_threshold: float


PROFILE_PRESETS: dict[ProfileName, EconomyProfile] = {
    "economy": EconomyProfile(
        name="economy",
        chunk_max_chars=1900,
        chunk_max_blocks=12,
        context_chars=160,
        max_context_entries=8,
        max_glossary_entries=12,
        max_tm_matches=3,
        tm_exact_threshold=0.995,
        tm_near_threshold=0.965,
        enable_editorial=False,
        enable_codex_qa=False,
        qa_on_risk_only=True,
        max_retries=1,
        strict_retry_mode=True,
        tier_b_threshold=0.40,
        tier_c_threshold=0.78,
    ),
    "balanced": EconomyProfile(
        name="balanced",
        chunk_max_chars=1400,
        chunk_max_blocks=8,
        context_chars=260,
        max_context_entries=12,
        max_glossary_entries=18,
        max_tm_matches=5,
        tm_exact_threshold=0.995,
        tm_near_threshold=0.93,
        enable_editorial=True,
        enable_codex_qa=True,
        qa_on_risk_only=True,
        max_retries=2,
        strict_retry_mode=False,
        tier_b_threshold=0.34,
        tier_c_threshold=0.68,
    ),
    "quality": EconomyProfile(
        name="quality",
        chunk_max_chars=1050,
        chunk_max_blocks=6,
        context_chars=360,
        max_context_entries=20,
        max_glossary_entries=28,
        max_tm_matches=8,
        tm_exact_threshold=0.995,
        tm_near_threshold=0.9,
        enable_editorial=True,
        enable_codex_qa=True,
        qa_on_risk_only=False,
        max_retries=3,
        strict_retry_mode=False,
        tier_b_threshold=0.30,
        tier_c_threshold=0.60,
    ),
}


def get_profile(name: ProfileName) -> EconomyProfile:
    """Return immutable profile settings by name."""

    return PROFILE_PRESETS[name]


def choose_default_profile(
    page_count: int,
    *,
    is_test_run: bool = False,
) -> ProfileName:
    """Pick default profile based on book size and run intent."""

    if is_test_run:
        return "economy"
    if page_count >= 450:
        return "economy"
    return "balanced"
