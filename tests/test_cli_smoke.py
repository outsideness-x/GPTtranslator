"""Smoke tests for GPTtranslate CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.cli import app

runner = CliRunner()


@pytest.mark.parametrize(
    "args, expected",
    [
        (["--help"], "Commands"),
        (["help"], "Commands"),
    ],
)
def test_help_outputs_command_section(args: list[str], expected: str) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert expected in result.stdout


@pytest.mark.parametrize(
    "command",
    ["help", "status", "init", "inspect", "extract", "glossary", "budget", "translate", "qa", "build", "version"],
)
def test_command_is_registered(command: str) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert command in result.stdout


def test_status_reports_not_initialized() -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "not initialized" in result.stdout.lower()


@pytest.mark.parametrize("command", ["qa", "build"])
def test_stub_commands(command: str) -> None:
    result = runner.invoke(app, [command])
    assert result.exit_code == 0
    assert "stub command" in result.stdout.lower()


def test_translate_help_includes_economy_flags() -> None:
    result = runner.invoke(app, ["translate", "--help"])
    assert result.exit_code == 0
    assert "--profile" in result.stdout
    assert "max-context" in result.stdout
    assert "--tm-first" in result.stdout
    assert "--no-editorial" in result.stdout
    assert "--qa-on-risk-only" in result.stdout
    assert "--reuse-cache" in result.stdout
    assert "--max-retries" in result.stdout
    assert "adaptive-chunk" in result.stdout
    assert "--budget-only" in result.stdout


def test_budget_help_includes_estimator_flags() -> None:
    result = runner.invoke(app, ["budget", "--help"])
    assert result.exit_code == 0
    assert "--profile" in result.stdout
    assert "max-context" in result.stdout
    assert "--tm-first" in result.stdout


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "gpttranslator 0.1.0" in result.stdout.lower()


def test_no_args_prints_banner() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "GPTtranslator CLI shell" in result.stdout
