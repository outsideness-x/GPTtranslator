"""Translate command registration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import typer

from ..core.config import load_config
from ..core.logging import get_logger
from ..core.manifest import load_book_manifest, save_book_manifest
from ..core.paths import resolve_workspace_root
from ..core.reporting import append_run_log, collect_book_run_summary, ensure_codex_logs, write_translation_summary
from ..translation.batching import BatchRunOptions, run_batch_translation
from ..translation.codex_backend import (
    BackendUnavailableError,
    build_translation_backend,
    parse_backend_name,
)
from ..translation.consistency import ConsistencyOptions, run_consistency_pass
from ..translation.economy import (
    EconomyDataError,
    EconomyPlanRequest,
    build_economy_plan,
    estimate_book_budget,
    load_book_economy_data,
    write_budget_report,
)
from ..translation.economy.budget import BudgetEstimate
from ..translation.economy.profiles import ProfileName
from ..translation.editor import EditorialOptions, run_editorial_pass


def register(app: typer.Typer) -> None:
    """Register `translate` command."""

    @app.command("translate")
    def translate_command(
        book_id: str = typer.Argument(..., help="Book ID from `gpttranslator init`."),
        profile: str | None = typer.Option(
            None,
            "--profile",
            help="Economy profile: economy|balanced|quality. Auto-selected when omitted.",
        ),
        max_context_entries: int | None = typer.Option(
            None,
            "--max-context-entries",
            min=1,
            help="Hard limit for compact context package entries.",
        ),
        tm_first: bool = typer.Option(
            True,
            "--tm-first/--no-tm-first",
            help="Use translation-memory-first routing before Codex calls.",
        ),
        no_editorial: bool = typer.Option(
            False,
            "--no-editorial",
            help="Disable optional editorial pass.",
        ),
        qa_on_risk_only: bool = typer.Option(
            True,
            "--qa-on-risk-only/--qa-all",
            help="Run Codex-based QA only for risky chunks.",
        ),
        reuse_cache: bool = typer.Option(
            True,
            "--reuse-cache/--no-reuse-cache",
            help="Reuse valid output.json by fingerprint cache hits.",
        ),
        max_retries: int | None = typer.Option(
            None,
            "--max-retries",
            min=1,
            help="Retry cap for recovery strategy.",
        ),
        adaptive_chunking: bool = typer.Option(
            True,
            "--adaptive-chunking/--fixed-chunking",
            help="Enable heuristic split/merge before tier routing.",
        ),
        batch_size: int = typer.Option(
            24,
            "--batch-size",
            min=1,
            help="Maximum chunks per batch for resilient chunked execution.",
        ),
        budget_only: bool = typer.Option(
            False,
            "--budget-only",
            help="Estimate budget and write artifacts without execution phase.",
        ),
        backend: str = typer.Option(
            "codex-cli",
            "--backend",
            help="Translation backend: codex-cli (default) or mock.",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Prepare jobs and backend wiring without invoking codex subprocess.",
        ),
        strict_json: bool = typer.Option(
            True,
            "--strict-json/--best-effort-json",
            help="Require strict validated output.json (recommended).",
        ),
        strict_terminology: bool = typer.Option(
            True,
            "--strict-terminology/--relaxed-terminology",
            help="Enforce glossary terminology strictly during editorial/consistency passes.",
        ),
        preserve_literalness: bool = typer.Option(
            False,
            "--preserve-literalness/--allow-free-rewrite",
            help="Keep closer literalness in editorial rewrite when enabled.",
        ),
        editorial_rewrite_level: str = typer.Option(
            "medium",
            "--editorial-rewrite-level",
            help="Editorial rewrite level: light|medium|aggressive.",
        ),
        resume: bool = typer.Option(
            False,
            "--resume",
            help="Resume translation from existing batch/checkpoint manifests.",
        ),
        from_batch: str | None = typer.Option(
            None,
            "--from-batch",
            help="Start execution from specific batch_id.",
        ),
        to_batch: str | None = typer.Option(
            None,
            "--to-batch",
            help="Stop execution at specific batch_id.",
        ),
        only_failed: bool = typer.Option(
            False,
            "--only-failed",
            help="Run only batches with failed status.",
        ),
    ) -> None:
        """Run cost-aware translation planning with economy observability."""

        config = load_config()
        logger = get_logger("commands.translate")
        workspace_root = resolve_workspace_root(config.project_root, config.workspace_dir_name)
        book_root = workspace_root / book_id

        append_run_log(
            book_root=book_root,
            stage="translate",
            status="started",
            message="Translation pipeline started.",
            details={
                "backend": backend,
                "dry_run": dry_run,
                "profile": profile or "auto",
                "batch_size": batch_size,
            },
        )
        ensure_codex_logs(book_root)

        try:
            backend_name = parse_backend_name(backend)
            backend_max_attempts = max_retries or config.default_max_retries
            selected_backend = build_translation_backend(
                backend=backend_name,
                codex_command=config.codex_command,
                timeout_seconds=120,
                max_attempts=backend_max_attempts,
                dry_run=dry_run,
            )
            if backend_name == "codex-cli" and not budget_only:
                if hasattr(selected_backend, "ensure_available") and not dry_run:
                    selected_backend.ensure_available()

            profile_name = _parse_profile_name(profile)
            rewrite_level = _parse_rewrite_level(editorial_rewrite_level)
            request = EconomyPlanRequest(
                profile=profile_name,
                max_context_entries=max_context_entries,
                tm_first=tm_first,
                no_editorial=no_editorial,
                qa_on_risk_only=qa_on_risk_only,
                reuse_cache=reuse_cache,
                max_retries=max_retries,
                adaptive_chunking=adaptive_chunking,
                is_test_run=budget_only,
            )

            data = load_book_economy_data(
                project_root=config.project_root,
                workspace_dir_name=config.workspace_dir_name,
                book_id=book_id,
            )
            budget_report = estimate_book_budget(data=data, request=request)
            budget_path = write_budget_report(data=data, report=budget_report, request=request)
        except (EconomyDataError, ValueError, BackendUnavailableError) as exc:
            append_run_log(
                book_root=book_root,
                stage="translate",
                status="failed",
                message=f"Translation setup failed: {exc}",
            )
            typer.secho(f"Translate failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        if budget_only:
            ensure_codex_logs(data.book_root)
            summary = collect_book_run_summary(data.book_root)
            summary_path = write_translation_summary(data.book_root, summary)
            append_run_log(
                book_root=data.book_root,
                stage="translate",
                status="budget_only",
                message="Budget-only planning completed.",
                details={"summary_path": str(summary_path)},
            )
            typer.secho("Budget-only translation planning completed", fg=typer.colors.GREEN)
            _print_budget_summary(
                book_id, budget_report.estimate, budget_path, selected=budget_report.selected_profile.name
            )
            return

        try:
            result = build_economy_plan(data=data, request=request)
        except (EconomyDataError, ValueError, OSError) as exc:
            append_run_log(
                book_root=data.book_root,
                stage="translate",
                status="failed",
                message=f"Economy planning failed: {exc}",
            )
            typer.secho(f"Translate failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        economy_summary = result.summary
        logger.info(
            "translate economy plan: book_id=%s profile=%s codex=%s tm_reuse=%s cache_hits=%s savings=%s%%",
            book_id,
            result.selected_profile.name,
            economy_summary.codex_chunks,
            economy_summary.tm_reuse_chunks,
            economy_summary.cache_hits,
            economy_summary.estimated_savings_percent(),
        )

        typer.secho("Translate economy planning completed", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID                     : {book_id}")
        typer.echo(f"  Backend                     : {backend_name}")
        typer.echo(f"  Dry-run backend mode        : {dry_run}")
        typer.echo(f"  Strict JSON mode            : {strict_json}")
        typer.echo(f"  Strict terminology          : {strict_terminology}")
        typer.echo(f"  Preserve literalness        : {preserve_literalness}")
        typer.echo(f"  Editorial rewrite level     : {rewrite_level}")
        typer.echo(f"  Batch size                  : {batch_size}")
        typer.echo(f"  Profile                     : {result.selected_profile.name}")
        typer.echo(f"  Chunks (before/after)       : {result.chunks_before}/{result.chunks_after}")
        typer.echo(f"  Chunks routed to Codex      : {economy_summary.codex_chunks}")
        typer.echo(f"  Translation-memory reuse    : {economy_summary.tm_reuse_chunks}")
        typer.echo(f"  Repeated local reuse        : {economy_summary.repeated_reuse_chunks}")
        typer.echo(f"  Job cache hits              : {economy_summary.cache_hits}")
        typer.echo(f"  Editorial jobs planned      : {economy_summary.editorial_jobs}")
        typer.echo(f"  Editorial skipped           : {economy_summary.editorial_skipped}")
        typer.echo(f"  QA jobs planned             : {economy_summary.qa_jobs}")
        typer.echo(f"  QA skipped                  : {economy_summary.qa_skipped}")
        typer.echo(f"  Retries avoided             : {economy_summary.retries_avoided}")
        typer.echo(f"  Avg context weight          : {economy_summary.avg_context_weight}")
        typer.echo(f"  Estimated savings           : {economy_summary.estimated_savings_percent()}%")
        typer.echo(f"  Economy plan artifact       : {result.plan_path}")
        typer.echo(f"  Economy summary artifact    : {result.summary_path}")
        typer.echo(f"  Budget estimate artifact    : {budget_path}")
        batch_options = BatchRunOptions(
            resume=resume,
            from_batch=from_batch,
            to_batch=to_batch,
            only_failed=only_failed,
            max_chunks_per_batch=batch_size,
        )
        translated_dir = data.book_root / "translated"
        logs_dir = data.book_root / "logs"
        typer.echo("  Execution mode              : batch processing with checkpoint/resume")
        typer.echo("  Batch processing started...")

        try:
            batch_result = run_batch_translation(
                book_id=book_id,
                plans=result.plans,
                translated_dir=translated_dir,
                logs_dir=logs_dir,
                backend=selected_backend,
                options=batch_options,
                timeout_seconds=120,
                max_attempts=backend_max_attempts,
                strict_json=strict_json,
                progress_callback=lambda message: typer.echo(f"    {message}"),
            )
        except (ValueError, OSError) as exc:
            append_run_log(
                book_root=data.book_root,
                stage="translate",
                status="failed",
                message=f"Batch execution failed: {exc}",
            )
            typer.secho(f"Translate failed during batch execution: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        typer.echo("  Batch execution completed")
        typer.echo(f"  Selected batches            : {len(batch_result.selected_batch_ids)}")
        typer.echo(f"  Target chunks               : {batch_result.total_target_chunks}")
        typer.echo(f"  Processed chunks            : {batch_result.processed_chunks}")
        typer.echo(f"  Completed chunks            : {batch_result.completed_chunks}")
        typer.echo(f"  Failed chunks               : {batch_result.failed_chunks}")
        typer.echo(f"  Skipped chunks              : {batch_result.skipped_chunks}")
        typer.echo(f"  Elapsed seconds             : {round(batch_result.elapsed_seconds, 1)}")
        typer.echo(f"  Batch manifest              : {batch_result.manifest_path}")
        typer.echo(f"  Chunk checkpoint            : {batch_result.checkpoint_path}")
        typer.echo(f"  Translated chunks           : {batch_result.translated_chunks_path}")
        typer.echo(f"  Codex jobs log              : {batch_result.codex_jobs_log_path}")
        typer.echo(f"  Codex failures log          : {batch_result.codex_failures_log_path}")

        typer.echo("  Editorial pass started...")
        editorial_result = run_editorial_pass(
            book_root=data.book_root,
            backend=selected_backend,
            options=EditorialOptions(
                strict_terminology=strict_terminology,
                preserve_literalness=preserve_literalness,
                rewrite_level=rewrite_level,
                resume=resume,
            ),
            progress_callback=lambda message: typer.echo(f"    {message}"),
        )
        typer.echo("  Editorial pass completed")
        typer.echo(f"  Editorial processed         : {editorial_result.processed_chunks}")
        typer.echo(f"  Editorial edited            : {editorial_result.edited_chunks}")
        typer.echo(f"  Editorial failed            : {editorial_result.failed_chunks}")
        typer.echo(f"  Editorial skipped           : {editorial_result.skipped_chunks}")
        typer.echo(f"  Edited chunks artifact      : {editorial_result.edited_chunks_path}")

        consistency_result = run_consistency_pass(
            book_root=data.book_root,
            options=ConsistencyOptions(
                strict_terminology=strict_terminology,
                preserve_literalness=preserve_literalness,
                rewrite_level=rewrite_level,
            ),
        )
        typer.echo("  Consistency pass completed")
        typer.echo(f"  Consistency checked chunks  : {consistency_result.checked_chunks}")
        typer.echo(f"  Consistency flags           : {consistency_result.flags_count}")
        typer.echo(f"  Consistency conflicts       : {consistency_result.conflict_count}")
        typer.echo(f"  Consistency flags artifact  : {consistency_result.flags_path}")

        logger.info(
            "translate batch run finished: batches=%s target_chunks=%s processed=%s completed=%s failed=%s skipped=%s",
            len(batch_result.selected_batch_ids),
            batch_result.total_target_chunks,
            batch_result.processed_chunks,
            batch_result.completed_chunks,
            batch_result.failed_chunks,
            batch_result.skipped_chunks,
        )

        ensure_codex_logs(data.book_root)
        run_summary = collect_book_run_summary(data.book_root)
        summary_path = write_translation_summary(data.book_root, run_summary)

        manifest_path = data.book_root / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = load_book_manifest(manifest_path)
                pipeline = manifest.metadata.setdefault("pipeline", {})
                pipeline["translate"] = "done" if batch_result.failed_chunks == 0 else "done_with_failures"
                manifest.metadata["stage"] = (
                    "translated" if batch_result.failed_chunks == 0 else "translated_with_failures"
                )
                manifest.metadata["translation"] = {
                    "processed_chunks": batch_result.processed_chunks,
                    "completed_chunks": batch_result.completed_chunks,
                    "failed_chunks": batch_result.failed_chunks,
                    "skipped_chunks": batch_result.skipped_chunks,
                    "codex_jobs": run_summary.codex_jobs_count,
                    "retries": run_summary.retries_count,
                    "consistency_flags": consistency_result.flags_count,
                    "summary_artifact": "output/translation_summary.md",
                }
                save_book_manifest(manifest_path, manifest)
            except Exception as exc:  # pragma: no cover - defensive manifest write protection
                logger.warning("unable to update manifest after translate: %s", exc)

        append_run_log(
            book_root=data.book_root,
            stage="translate",
            status="completed",
            message="Translation pipeline completed.",
            details={
                "chunks": run_summary.chunk_count,
                "codex_jobs": run_summary.codex_jobs_count,
                "retries": run_summary.retries_count,
                "summary_path": str(summary_path),
            },
        )
        typer.echo(f"  Translation summary artifact: {summary_path}")
        _print_budget_summary(
            book_id, budget_report.estimate, budget_path, selected=budget_report.selected_profile.name
        )


def _parse_profile_name(profile: str | None) -> ProfileName | None:
    if profile is None:
        return None
    value = profile.strip().lower()
    if not value:
        return None
    allowed: tuple[ProfileName, ...] = ("economy", "balanced", "quality")
    if value not in allowed:
        allowed_text = ", ".join(allowed)
        raise ValueError(f"invalid profile '{profile}'; expected one of: {allowed_text}")
    return cast(ProfileName, value)


def _parse_rewrite_level(value: str) -> Literal["light", "medium", "aggressive"]:
    normalized = value.strip().lower()
    allowed: tuple[Literal["light", "medium", "aggressive"], ...] = ("light", "medium", "aggressive")
    if normalized not in allowed:
        allowed_text = ", ".join(allowed)
        raise ValueError(f"invalid editorial_rewrite_level '{value}'; expected one of: {allowed_text}")
    return cast(Literal["light", "medium", "aggressive"], normalized)


def _print_budget_summary(book_id: str, estimate: BudgetEstimate, artifact_path: Path, *, selected: str) -> None:
    typer.echo("  Budget Snapshot:")
    typer.echo(f"    Profile selected          : {selected}")
    typer.echo(f"    Estimated chunks          : {estimate.estimated_chunk_count}")
    typer.echo(f"    Estimated Codex jobs      : {estimate.estimated_codex_job_count}")
    typer.echo(f"    Heavy jobs                : {estimate.estimated_heavy_job_count}")
    typer.echo(f"    Retries risk              : {estimate.estimated_retries_risk}")
    typer.echo(f"    Session pressure          : {estimate.session_pressure}")
    typer.echo(f"    Recommended profile       : {estimate.recommended_profile}")
    warnings = list(estimate.warnings)
    if warnings:
        typer.echo("    Warnings:")
        for warning in warnings:
            typer.echo(f"      - {warning}")
    typer.echo(f"    Budget artifact           : {artifact_path}")
    typer.echo(f"    Book ID                   : {book_id}")
