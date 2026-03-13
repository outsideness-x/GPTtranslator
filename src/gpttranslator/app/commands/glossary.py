"""Glossary command registration."""

from __future__ import annotations

import typer

from ..core.config import load_config
from ..core.paths import build_book_workspace_paths, resolve_workspace_root
from ..memory.glossary_manager import ensure_glossary_template, find_in_glossary, validate_glossary_structure
from ..memory.style_guide_manager import (
    ensure_chapter_notes_template,
    ensure_style_guide_template,
    validate_chapter_notes_structure,
    validate_style_guide_structure,
)
from ..memory.translation_memory_manager import (
    ensure_translation_memory_file,
    find_in_translation_memory,
    validate_translation_memory,
)


def register(app: typer.Typer) -> None:
    """Register `glossary` command."""

    @app.command("glossary")
    def glossary_command(
        book_id: str = typer.Argument(..., help="Book ID from `gpttranslator init`."),
        find: str | None = typer.Option(None, "--find", help="Search term in glossary and translation memory."),
        limit: int = typer.Option(8, min=1, max=50, help="Maximum matches for --find."),
    ) -> None:
        """Manage and validate local project memory files."""
        config = load_config()
        workspace_root = resolve_workspace_root(config.project_root, config.workspace_dir_name)
        paths = build_book_workspace_paths(workspace_root, book_id)

        if not paths.root.exists() or not paths.root.is_dir():
            typer.secho(f"Glossary failed: book workspace not found: {book_id}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        if not paths.memory_dir.exists():
            typer.secho(
                f"Glossary failed: memory directory is missing: {paths.memory_dir}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)

        created: list[str] = []
        if ensure_glossary_template(paths.glossary_path, book_id):
            created.append("glossary.md")
        if ensure_style_guide_template(paths.style_guide_path, book_id):
            created.append("style_guide.md")
        if ensure_chapter_notes_template(paths.chapter_notes_path, book_id):
            created.append("chapter_notes.md")
        if ensure_translation_memory_file(paths.translation_memory_path):
            created.append("translation_memory.jsonl")

        glossary_validation = validate_glossary_structure(paths.glossary_path)
        style_validation = validate_style_guide_structure(paths.style_guide_path)
        chapter_validation = validate_chapter_notes_structure(paths.chapter_notes_path)
        tm_validation = validate_translation_memory(paths.translation_memory_path)

        validation_issues = [
            *glossary_validation.issues,
            *style_validation.issues,
            *chapter_validation.issues,
            *tm_validation.issues,
        ]

        color = typer.colors.GREEN if not validation_issues else typer.colors.YELLOW
        typer.secho("Memory summary", fg=color)
        typer.echo(f"  Book ID                : {book_id}")
        typer.echo(f"  Glossary terms         : {glossary_validation.term_count}")
        typer.echo(f"  Translation memory rows: {tm_validation.record_count}")
        typer.echo(f"  Glossary file          : {paths.glossary_path}")
        typer.echo(f"  Style guide file       : {paths.style_guide_path}")
        typer.echo(f"  Chapter notes file     : {paths.chapter_notes_path}")
        typer.echo(f"  TM file                : {paths.translation_memory_path}")

        if created:
            typer.echo(f"  Templates created      : {', '.join(created)}")
        else:
            typer.echo("  Templates created      : none")

        if find:
            glossary_hits = find_in_glossary(paths.glossary_path, find, limit=limit)
            tm_hits = find_in_translation_memory(paths.translation_memory_path, find, limit=limit)
            typer.echo(f"  Search query           : {find}")
            typer.echo(f"  Glossary matches       : {len(glossary_hits)}")
            for glossary_match in glossary_hits:
                typer.echo(f"    - {glossary_match.source_term} -> {glossary_match.target_term}")
            typer.echo(f"  TM matches             : {len(tm_hits)}")
            for tm_match in tm_hits:
                typer.echo(f"    - {tm_match.source_text} -> {tm_match.target_text}")

        if validation_issues:
            typer.secho("Validation issues:", fg=typer.colors.YELLOW)
            for issue in validation_issues:
                typer.echo(f"  - {issue}")
