"""Translate command registration."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import typer

from ..core.config import load_config
from ..core.logging import get_logger
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
        budget_only: bool = typer.Option(
            False,
            "--budget-only",
            help="Estimate budget and write artifacts without execution phase.",
        ),
    ) -> None:
        """Run cost-aware translation planning with economy observability."""

        config = load_config()
        logger = get_logger("commands.translate")

        try:
            profile_name = _parse_profile_name(profile)
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
        except (EconomyDataError, ValueError) as exc:
            typer.secho(f"Translate failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        if budget_only:
            typer.secho("Budget-only translation planning completed", fg=typer.colors.GREEN)
            _print_budget_summary(book_id, budget_report.estimate, budget_path, selected=budget_report.selected_profile.name)
            return

        try:
            result = build_economy_plan(data=data, request=request)
        except (EconomyDataError, ValueError, OSError) as exc:
            typer.secho(f"Translate failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        summary = result.summary
        logger.info(
            "translate economy plan: book_id=%s profile=%s codex=%s tm_reuse=%s cache_hits=%s savings=%s%%",
            book_id,
            result.selected_profile.name,
            summary.codex_chunks,
            summary.tm_reuse_chunks,
            summary.cache_hits,
            summary.estimated_savings_percent(),
        )

        typer.secho("Translate economy planning completed", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID                     : {book_id}")
        typer.echo(f"  Profile                     : {result.selected_profile.name}")
        typer.echo(f"  Chunks (before/after)       : {result.chunks_before}/{result.chunks_after}")
        typer.echo(f"  Chunks routed to Codex      : {summary.codex_chunks}")
        typer.echo(f"  Translation-memory reuse    : {summary.tm_reuse_chunks}")
        typer.echo(f"  Repeated local reuse        : {summary.repeated_reuse_chunks}")
        typer.echo(f"  Job cache hits              : {summary.cache_hits}")
        typer.echo(f"  Editorial jobs planned      : {summary.editorial_jobs}")
        typer.echo(f"  Editorial skipped           : {summary.editorial_skipped}")
        typer.echo(f"  QA jobs planned             : {summary.qa_jobs}")
        typer.echo(f"  QA skipped                  : {summary.qa_skipped}")
        typer.echo(f"  Retries avoided             : {summary.retries_avoided}")
        typer.echo(f"  Avg context weight          : {summary.avg_context_weight}")
        typer.echo(f"  Estimated savings           : {summary.estimated_savings_percent()}%")
        typer.echo(f"  Economy plan artifact       : {result.plan_path}")
        typer.echo(f"  Economy summary artifact    : {result.summary_path}")
        typer.echo(f"  Budget estimate artifact    : {budget_path}")
        typer.echo("  Execution mode              : planning-only (Codex execution is not run in this stage)")
        _print_budget_summary(book_id, budget_report.estimate, budget_path, selected=budget_report.selected_profile.name)


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
