"""Codex CLI backend with strict file-based protocol contract."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from ...core.models import CodexJob, CodexResult
from .base import BaseTranslationBackend
from ..protocol import (
    CodexJobPaths,
    build_initial_meta_payload,
    is_retryable_failure,
    load_and_validate_output_json,
    utcnow_iso,
    write_json_file,
)

CommandBuilder = Callable[[CodexJob], Sequence[str]]


@dataclass(slots=True)
class _AttemptOutcome:
    attempt: int
    started_at: str
    finished_at: str
    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    failure_reason: str | None = None
    error_message: str | None = None


class CodexCliBackend(BaseTranslationBackend):
    """Shell-out backend that exchanges data through job artifact files."""

    backend_name = "codex_cli"

    def __init__(
        self,
        codex_command: str = "codex",
        timeout_seconds: int = 120,
        max_attempts: int = 3,
        command_builder: CommandBuilder | None = None,
    ) -> None:
        self.codex_command = codex_command
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.command_builder = command_builder

    def healthcheck(self) -> bool:
        """Check whether Codex CLI is available in PATH."""

        return shutil.which(self.codex_command) is not None

    def run_job(self, job: CodexJob) -> CodexResult:
        """Run one Codex job using only file-based input/output contract."""

        paths = self._normalize_job_paths(job)
        timeout_seconds = max(1, int(job.timeout_seconds or self.timeout_seconds))
        max_attempts = max(1, int(job.max_attempts or self.max_attempts))

        meta = self._load_or_init_meta(paths=paths, timeout_seconds=timeout_seconds, max_attempts=max_attempts)
        meta["status"] = "running"
        meta["updated_at"] = utcnow_iso()
        meta["timeout_seconds"] = timeout_seconds
        meta["max_attempts"] = max_attempts
        self._save_meta(paths.meta_json, meta)

        last_outcome: _AttemptOutcome | None = None
        for attempt in range(1, max_attempts + 1):
            outcome = self._run_attempt(job=job, paths=paths, attempt=attempt, timeout_seconds=timeout_seconds)
            last_outcome = outcome
            retry_scheduled = (
                outcome.failure_reason is not None
                and is_retryable_failure(outcome.failure_reason)
                and attempt < max_attempts
            )
            self._append_attempt_logs(paths, outcome)
            self._append_meta_attempt(meta, outcome, retry_scheduled)

            if outcome.failure_reason is None:
                meta["status"] = "succeeded"
                meta["updated_at"] = utcnow_iso()
                self._save_meta(paths.meta_json, meta)
                return CodexResult(
                    job_id=job.job_id,
                    return_code=outcome.return_code,
                    stdout=outcome.stdout,
                    stderr=outcome.stderr,
                    success=True,
                    output_path=str(paths.output_json),
                    meta_path=str(paths.meta_json),
                    attempt_count=attempt,
                )

            if not retry_scheduled:
                break

        if last_outcome is None:
            last_outcome = _AttemptOutcome(
                attempt=0,
                started_at=utcnow_iso(),
                finished_at=utcnow_iso(),
                command=[],
                return_code=1,
                stdout="",
                stderr="",
                failure_reason="process_spawn_error",
                error_message="No attempt was executed.",
            )

        meta["status"] = "failed"
        meta["updated_at"] = utcnow_iso()
        meta["failure_reason"] = last_outcome.failure_reason
        if last_outcome.error_message:
            meta["failure_message"] = last_outcome.error_message
        self._save_meta(paths.meta_json, meta)

        return CodexResult(
            job_id=job.job_id,
            return_code=last_outcome.return_code,
            stdout=last_outcome.stdout,
            stderr=last_outcome.stderr,
            success=False,
            output_path=str(paths.output_json),
            failure_reason=last_outcome.failure_reason,
            meta_path=str(paths.meta_json),
            attempt_count=last_outcome.attempt,
        )

    def _run_attempt(
        self,
        job: CodexJob,
        paths: CodexJobPaths,
        attempt: int,
        timeout_seconds: int,
    ) -> _AttemptOutcome:
        started_at = utcnow_iso()
        command = list(self._build_command(job))
        paths.output_json.unlink(missing_ok=True)

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            finished_at = utcnow_iso()
            return _AttemptOutcome(
                attempt=attempt,
                started_at=started_at,
                finished_at=finished_at,
                command=command,
                return_code=124,
                stdout=_decode_stream(exc.stdout),
                stderr=_decode_stream(exc.stderr),
                failure_reason="timeout",
                error_message=f"Codex job timed out after {timeout_seconds} seconds.",
            )
        except KeyboardInterrupt:
            finished_at = utcnow_iso()
            return _AttemptOutcome(
                attempt=attempt,
                started_at=started_at,
                finished_at=finished_at,
                command=command,
                return_code=130,
                stdout="",
                stderr="Codex process interrupted by keyboard signal.",
                failure_reason="interrupted_process",
                error_message="Codex process interrupted by keyboard signal.",
            )
        except OSError as exc:
            finished_at = utcnow_iso()
            return _AttemptOutcome(
                attempt=attempt,
                started_at=started_at,
                finished_at=finished_at,
                command=command,
                return_code=1,
                stdout="",
                stderr=str(exc),
                failure_reason="process_spawn_error",
                error_message=f"Failed to start Codex process: {exc}",
            )

        finished_at = utcnow_iso()
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""

        if completed.returncode < 0:
            signal_number = abs(completed.returncode)
            return _AttemptOutcome(
                attempt=attempt,
                started_at=started_at,
                finished_at=finished_at,
                command=command,
                return_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                failure_reason="interrupted_process",
                error_message=f"Codex process terminated by signal {signal_number}.",
            )

        if completed.returncode != 0:
            return _AttemptOutcome(
                attempt=attempt,
                started_at=started_at,
                finished_at=finished_at,
                command=command,
                return_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                failure_reason="process_exit_nonzero",
                error_message=f"Codex process exited with return code {completed.returncode}.",
            )

        output_result = load_and_validate_output_json(paths.output_json, expected_job_id=job.job_id)
        if output_result.failure_reason is not None:
            return _AttemptOutcome(
                attempt=attempt,
                started_at=started_at,
                finished_at=finished_at,
                command=command,
                return_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                failure_reason=output_result.failure_reason,
                error_message=output_result.error_message,
            )

        return _AttemptOutcome(
            attempt=attempt,
            started_at=started_at,
            finished_at=finished_at,
            command=command,
            return_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def _normalize_job_paths(self, job: CodexJob) -> CodexJobPaths:
        if not job.output_path:
            raise ValueError("CodexJob.output_path must be set.")

        output_json = Path(job.output_path).resolve()
        job_dir = output_json.parent
        prompt_md = Path(job.prompt_path).resolve() if job.prompt_path else (job_dir / "prompt.md")
        input_json = Path(job.input_path).resolve() if job.input_path else (job_dir / "input.json")
        raw_stdout = Path(job.raw_stdout_path).resolve() if job.raw_stdout_path else (job_dir / "raw_stdout.txt")
        raw_stderr = Path(job.raw_stderr_path).resolve() if job.raw_stderr_path else (job_dir / "raw_stderr.txt")
        meta_json = Path(job.meta_path).resolve() if job.meta_path else (job_dir / "meta.json")

        job.prompt_path = str(prompt_md)
        job.input_path = str(input_json)
        job.output_path = str(output_json)
        job.raw_stdout_path = str(raw_stdout)
        job.raw_stderr_path = str(raw_stderr)
        job.meta_path = str(meta_json)

        job_dir.mkdir(parents=True, exist_ok=True)
        raw_stdout.touch(exist_ok=True)
        raw_stderr.touch(exist_ok=True)
        input_json.touch(exist_ok=True)
        prompt_md.touch(exist_ok=True)

        return CodexJobPaths(
            job_dir=job_dir,
            input_json=input_json,
            prompt_md=prompt_md,
            output_json=output_json,
            raw_stdout=raw_stdout,
            raw_stderr=raw_stderr,
            meta_json=meta_json,
        )

    def _load_or_init_meta(
        self,
        paths: CodexJobPaths,
        timeout_seconds: int,
        max_attempts: int,
    ) -> dict[str, object]:
        if paths.meta_json.exists():
            try:
                payload = json.loads(paths.meta_json.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    payload.setdefault("attempts", [])
                    return payload
            except json.JSONDecodeError:
                pass

        book_id = self._book_id_from_job_dir(paths.job_dir)
        job_id = paths.job_dir.name
        payload = build_initial_meta_payload(
            book_id=book_id,
            job_id=job_id,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        self._save_meta(paths.meta_json, payload)
        return payload

    def _append_attempt_logs(self, paths: CodexJobPaths, outcome: _AttemptOutcome) -> None:
        header = (
            f"=== attempt {outcome.attempt} "
            f"started_at={outcome.started_at} finished_at={outcome.finished_at} "
            f"return_code={outcome.return_code} ===\n"
        )
        self._append_text(paths.raw_stdout, header + outcome.stdout + "\n")
        self._append_text(paths.raw_stderr, header + outcome.stderr + "\n")

    def _append_meta_attempt(
        self,
        meta: dict[str, object],
        outcome: _AttemptOutcome,
        retry_scheduled: bool,
    ) -> None:
        attempts_raw = meta.setdefault("attempts", [])
        if not isinstance(attempts_raw, list):
            attempts_raw = []
            meta["attempts"] = attempts_raw

        attempts_raw.append(
            {
                "attempt": outcome.attempt,
                "started_at": outcome.started_at,
                "finished_at": outcome.finished_at,
                "command": outcome.command,
                "return_code": outcome.return_code,
                "outcome": outcome.failure_reason or "success",
                "message": outcome.error_message or "",
                "retry_scheduled": retry_scheduled,
            }
        )

        meta["updated_at"] = utcnow_iso()
        if outcome.failure_reason is not None:
            meta["last_failure_reason"] = outcome.failure_reason
            if outcome.error_message:
                meta["last_failure_message"] = outcome.error_message

    def _save_meta(self, meta_json: Path, payload: dict[str, object]) -> None:
        write_json_file(meta_json, payload)

    def _build_command(self, job: CodexJob) -> Sequence[str]:
        if self.command_builder is not None:
            command = list(self.command_builder(job))
            if not command:
                raise ValueError("Codex command builder returned an empty command.")
            return command
        return [self.codex_command, "exec", "--prompt-file", job.prompt_path]

    def _book_id_from_job_dir(self, job_dir: Path) -> str:
        # Expected layout: workspace/<book_id>/jobs/<job_id>
        if len(job_dir.parents) >= 2:
            return job_dir.parents[1].name
        return "unknown-book"

    def _append_text(self, path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as file:
            file.write(text)


def _decode_stream(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
