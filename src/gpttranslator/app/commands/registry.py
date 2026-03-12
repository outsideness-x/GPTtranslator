"""Aggregate registration of CLI commands."""

from __future__ import annotations

from collections.abc import Callable

import typer

from .budget import register as register_budget
from .build import register as register_build
from .extract import register as register_extract
from .glossary import register as register_glossary
from .help import register as register_help
from .init import register as register_init
from .inspect import register as register_inspect
from .qa import register as register_qa
from .status import register as register_status
from .translate import register as register_translate
from .version import register as register_version

CommandRegistrar = Callable[[typer.Typer], None]


def register_commands(app: typer.Typer) -> None:
    """Register all top-level CLI commands."""

    registrars: tuple[CommandRegistrar, ...] = (
        register_help,
        register_status,
        register_init,
        register_inspect,
        register_extract,
        register_glossary,
        register_budget,
        register_translate,
        register_qa,
        register_build,
        register_version,
    )

    for register in registrars:
        register(app)
