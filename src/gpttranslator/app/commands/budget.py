"""Budget command registration."""

from __future__ import annotations

from typing import cast

import typer

from ..core.config import load_config
from ..translation.economy import (
    EconomyDataError,
    EconomyPlanRequest,
    estimate_book_budget,
    load_book_economy_data,
    write_budget_report,
)
from ..translation.economy.profiles import ProfileName


def register(app: typer.Typer) -> None:
    """Register `budget` command."""

    @app.command("budget")
    def budget_command(
        book_id: str = typer.Argument(..., help="Book ID from `gpttranslator init`."),
        profile: str | None = typer.Option(
            None,
            "--profile",
            help="Economy profile override: economy|balanced|quality.",
        ),
        max_context_entries: int | None = typer.Option(
            None,
            "--max-context-entries",
            min=1,
            help="Context entry cap used by estimator.",
        ),
        tm_first: bool = typer.Option(
            True,
            "--tm-first/--no-tm-first",
            help="Enable TM-first planning in estimator.",
        ),
        no_editorial: bool = typer.Option(
            False,
            "--no-editorial",
            help="Disable editorial-pass projection.",
        ),
        qa_on_risk_only: bool = typer.Option(
            True,
            "--qa-on-risk-only/--qa-all",
            help="Estimate QA only for risky chunks.",
        ),
        adaptive_chunking: bool = typer.Option(
            True,
            "--adaptive-chunking/--fixed-chunking",
            help="Enable adaptive split/merge in estimator.",
        ),
    ) -> None:
        """Estimate Codex usage pressure without token APIs."""

        config = load_config()

        try:
            profile_name = _parse_profile_name(profile)
            request = EconomyPlanRequest(
                profile=profile_name,
                max_context_entries=max_context_entries,
                tm_first=tm_first,
                no_editorial=no_editorial,
                qa_on_risk_only=qa_on_risk_only,
                adaptive_chunking=adaptive_chunking,
                is_test_run=True,
            )
            data = load_book_economy_data(
                project_root=config.project_root,
                workspace_dir_name=config.workspace_dir_name,
                book_id=book_id,
            )
            report = estimate_book_budget(data=data, request=request)
            artifact_path = write_budget_report(data=data, report=report, request=request)
        except (EconomyDataError, ValueError) as exc:
            typer.secho(f"Budget failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        estimate = report.estimate
        typer.secho("Budget estimate completed", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID                     : {book_id}")
        typer.echo(f"  Profile selected            : {report.selected_profile.name}")
        typer.echo(f"  Estimated chunks            : {estimate.estimated_chunk_count}")
        typer.echo(f"  Estimated Codex jobs        : {estimate.estimated_codex_job_count}")
        typer.echo(f"  Estimated heavy jobs        : {estimate.estimated_heavy_job_count}")
        typer.echo(f"  Estimated editorial jobs    : {estimate.estimated_editorial_job_count}")
        typer.echo(f"  Estimated QA jobs           : {estimate.estimated_qa_job_count}")
        typer.echo(f"  Estimated local reuse       : {estimate.estimated_local_reuse_count}")
        typer.echo(f"  Average chunk chars         : {estimate.average_chunk_chars}")
        typer.echo(f"  Expected context weight     : {estimate.expected_context_weight}")
        typer.echo(f"  Retries risk                : {estimate.estimated_retries_risk}")
        typer.echo(f"  Session pressure            : {estimate.session_pressure}")
        typer.echo(f"  Recommended profile         : {estimate.recommended_profile}")
        typer.echo(f"  Budget artifact             : {artifact_path}")
        for warning in estimate.warnings:
            typer.echo(f"  Warning                     : {warning}")


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
