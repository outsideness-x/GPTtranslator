"""Economical retry directives for Codex job failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RetryStrategy = Literal["none", "repair_json", "reduce_chunk", "lightweight_recovery"]


@dataclass(frozen=True, slots=True)
class RetryDirective:
    """Action to take on a failed job attempt."""

    retry: bool
    strategy: RetryStrategy
    next_template_id: str | None
    message: str


def decide_retry_directive(
    *,
    failure_reason: str | None,
    attempt: int,
    max_attempts: int,
    strict_mode: bool,
) -> RetryDirective:
    """Choose retry strategy that minimizes blind re-runs."""

    if failure_reason is None:
        return RetryDirective(False, "none", None, "Job succeeded; retry is not needed.")

    if attempt >= max_attempts:
        return RetryDirective(False, "none", None, "Retry budget exhausted.")

    if failure_reason in {"invalid_json", "partial_json"}:
        return RetryDirective(True, "repair_json", "translate_chunk", "Use compact repair-mode prompt.")

    if failure_reason == "output_schema_validation_failed":
        return RetryDirective(True, "lightweight_recovery", "translate_chunk", "Run lightweight schema recovery.")

    if failure_reason == "timeout":
        return RetryDirective(True, "reduce_chunk", None, "Reduce chunk size before next attempt.")

    if failure_reason == "interrupted_process":
        if strict_mode:
            return RetryDirective(False, "none", None, "Strict mode avoids retry after interruption.")
        return RetryDirective(True, "lightweight_recovery", "translate_chunk", "Retry once with lightweight context.")

    if failure_reason == "missing_output_file":
        if strict_mode:
            return RetryDirective(False, "none", None, "Strict mode avoids blind rerun on missing output.")
        return RetryDirective(True, "lightweight_recovery", "translate_chunk", "Retry with explicit file-write instructions.")

    return RetryDirective(False, "none", None, f"No retry strategy for failure reason: {failure_reason}")
