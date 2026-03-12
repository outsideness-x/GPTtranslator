"""Codex CLI translation backend stub."""

from __future__ import annotations

import shutil

from ...core.models import CodexJob, CodexResult
from .base import BaseTranslationBackend


class CodexCliBackend(BaseTranslationBackend):
    """Future backend that will shell out to the `codex` executable."""

    backend_name = "codex_cli"

    def __init__(self, codex_command: str = "codex") -> None:
        self.codex_command = codex_command

    def healthcheck(self) -> bool:
        """Check whether Codex CLI is available in PATH."""

        return shutil.which(self.codex_command) is not None

    def run_job(self, job: CodexJob) -> CodexResult:
        """Return stub result until runtime integration is enabled."""

        return CodexResult(
            job_id=job.job_id,
            return_code=1,
            stdout="",
            stderr="Codex CLI runtime is not implemented in this stage.",
            success=False,
            output_path=job.output_path,
        )
