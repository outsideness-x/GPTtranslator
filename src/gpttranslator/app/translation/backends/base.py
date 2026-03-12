"""Abstract translation backend contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ...core.models import CodexJob, CodexResult


class BaseTranslationBackend(ABC):
    """Common interface for pluggable translation backends."""

    backend_name: str = "base"

    @abstractmethod
    def healthcheck(self) -> bool:
        """Return backend readiness without running translation."""

    @abstractmethod
    def run_job(self, job: CodexJob) -> CodexResult:
        """Run one translation job and return normalized result."""
