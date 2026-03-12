"""QA command registration."""

from __future__ import annotations

import json

import typer

from ..core.config import load_config
from ..core.paths import resolve_workspace_root
from ..qa import QAOptions, run_qa_pass
from ..translation.codex_backend import BackendUnavailableError, build_translation_backend, parse_backend_name


def register(app: typer.Typer) -> None:
    """Register `qa` command."""

    @app.command("qa")
    def qa_command(
        book_id: str = typer.Argument(..., help="Book ID from `gpttranslator init`."),
        codex_based: bool = typer.Option(
            False,
            "--codex-based/--local-only",
            help="Enable optional Codex-based semantic/terminology QA checks.",
        ),
        codex_on_risk_only: bool = typer.Option(
            True,
            "--codex-on-risk-only/--codex-on-all",
            help="Run Codex QA only for risky chunks when enabled.",
        ),
        backend: str = typer.Option(
            "codex-cli",
            "--backend",
            help="Backend for optional Codex QA: codex-cli (default) or mock.",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Prepare Codex jobs without invoking subprocesses.",
        ),
        strict_terminology: bool = typer.Option(
            True,
            "--strict-terminology/--relaxed-terminology",
            help="Treat terminology inconsistencies as high-priority QA risks.",
        ),
        max_retries: int = typer.Option(
            2,
            "--max-retries",
            min=1,
            help="Retry cap for optional Codex QA jobs.",
        ),
        timeout_seconds: int = typer.Option(
            90,
            "--timeout-seconds",
            min=1,
            help="Timeout per optional Codex QA job.",
        ),
    ) -> None:
        """Run QA checks on translated chunks."""

        config = load_config()
        workspace_root = resolve_workspace_root(config.project_root, config.workspace_dir_name)
        book_root = workspace_root / book_id

        if not book_root.exists() or not book_root.is_dir():
            typer.secho(f"QA failed: book workspace not found: {book_root}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        selected_backend = None
        backend_name = "local-only"

        if codex_based:
            try:
                parsed_backend_name = parse_backend_name(backend)
                selected_backend = build_translation_backend(
                    backend=parsed_backend_name,
                    codex_command=config.codex_command,
                    timeout_seconds=timeout_seconds,
                    max_attempts=max_retries,
                    dry_run=dry_run,
                )
                backend_name = parsed_backend_name
                if parsed_backend_name == "codex-cli" and hasattr(selected_backend, "ensure_available") and not dry_run:
                    selected_backend.ensure_available()
            except (ValueError, BackendUnavailableError) as exc:
                typer.secho(f"QA failed: {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)

        try:
            result = run_qa_pass(
                book_root=book_root,
                options=QAOptions(
                    codex_enabled=codex_based,
                    codex_on_risk_only=codex_on_risk_only,
                    strict_terminology=strict_terminology,
                    timeout_seconds=timeout_seconds,
                    max_attempts=max_retries,
                ),
                backend=selected_backend,
                progress_callback=lambda message: typer.echo(f"    {message}"),
            )
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            typer.secho(f"QA failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        typer.secho("QA completed", fg=typer.colors.GREEN)
        typer.echo(f"  Book ID                     : {book_id}")
        typer.echo(f"  Source artifact             : {result.source_artifact}")
        typer.echo(f"  Codex mode                  : {codex_based}")
        typer.echo(f"  Backend                     : {backend_name}")
        typer.echo(f"  Expected chunks             : {result.total_chunks}")
        typer.echo(f"  Chunks with translation     : {result.translated_chunks}")
        typer.echo(f"  Missing translations        : {result.missing_chunks}")
        typer.echo(f"  Local QA flags              : {result.local_flags_count}")
        typer.echo(f"  Codex QA flags              : {result.codex_flags_count}")
        typer.echo(f"  Total QA flags              : {result.total_flags_count}")
        typer.echo(f"  High/Medium/Low             : {result.high_severity_count}/{result.medium_severity_count}/{result.low_severity_count}")
        typer.echo(f"  Codex semantic jobs         : {result.codex_semantic_jobs}")
        typer.echo(f"  Codex terminology jobs      : {result.codex_terminology_jobs}")
        typer.echo(f"  Codex failed jobs           : {result.codex_failed_jobs}")
        typer.echo(f"  Elapsed seconds             : {round(result.elapsed_seconds, 1)}")
        typer.echo(f"  QA flags artifact           : {result.qa_flags_path}")
        typer.echo(f"  QA report artifact          : {result.qa_report_path}")
