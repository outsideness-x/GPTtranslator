"""Tests for QA service and `gpttranslator qa` command."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpttranslator.app.qa import QAOptions, run_qa_pass
from gpttranslator.app.translation.codex_backend import MockCodexBackend
from gpttranslator.cli import app

runner = CliRunner()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _prepare_book_root(root: Path, book_id: str) -> Path:
    book_root = root / "workspace" / book_id
    (book_root / "analysis").mkdir(parents=True, exist_ok=True)
    (book_root / "memory").mkdir(parents=True, exist_ok=True)
    (book_root / "translated").mkdir(parents=True, exist_ok=True)
    (book_root / "output").mkdir(parents=True, exist_ok=True)
    (book_root / "logs").mkdir(parents=True, exist_ok=True)
    return book_root


def test_run_qa_pass_local_checks_write_flags_and_report(tmp_path: Path) -> None:
    book_root = _prepare_book_root(tmp_path, "book-qa-local")

    _write_jsonl(
        book_root / "analysis" / "chunks.jsonl",
        [
            {
                "chunk_id": "chunk-1",
                "chapter_id": "chapter-01",
                "page_range": [1, 1],
                "block_ids": ["b1"],
                "chunk_type": "paragraph_group",
                "source_text": "On 2024-05-10 equation E=mc2 and link https://example.com [1].",
                "footnote_refs": [{"marker": "[1]"}],
            },
            {
                "chunk_id": "chunk-2",
                "chapter_id": "chapter-01",
                "page_range": [1, 1],
                "block_ids": ["b2"],
                "chunk_type": "paragraph_group",
                "source_text": "Second source segment.",
                "footnote_refs": [],
            },
            {
                "chunk_id": "chunk-3",
                "chapter_id": "chapter-01",
                "page_range": [1, 1],
                "block_ids": ["b3"],
                "chunk_type": "paragraph_group",
                "source_text": "Third source [2].",
                "footnote_refs": [{"marker": "[2]"}],
            },
        ],
    )

    _write_jsonl(
        book_root / "translated" / "translated_chunks.jsonl",
        [
            {
                "chunk_id": "chunk-1",
                "status": "completed",
                "target_text": "В 2024 году часть содержимого была изменена.",
            },
            {
                "chunk_id": "chunk-2",
                "status": "completed",
                "target_text": "",
            },
        ],
    )

    (book_root / "memory" / "glossary.md").write_text(
        "# Glossary\n\n## Term Table\n| Source term | Target term | POS | Decision | Notes |\n|---|---|---|---|---|\n| equation | уравнение | noun | preferred | |\n",
        encoding="utf-8",
    )
    (book_root / "memory" / "style_guide.md").write_text("# Style Guide\n- Keep concise.\n", encoding="utf-8")
    (book_root / "memory" / "chapter_notes.md").write_text(
        "# Chapter Notes\n\n## Global Notes\n- Preserve markers.\n", encoding="utf-8"
    )

    result = run_qa_pass(
        book_root=book_root,
        options=QAOptions(codex_enabled=False),
    )

    assert result.total_chunks == 3
    assert result.missing_chunks >= 1
    assert result.local_flags_count >= 4

    flags = _read_jsonl(book_root / "translated" / "qa_flags.jsonl")
    rule_ids = {str(item.get("rule_id", "")) for item in flags}
    assert "missing_translation" in rule_ids
    assert "empty_translation" in rule_ids
    assert "footnote_marker_missing" in rule_ids
    assert "link_missing" in rule_ids

    report_text = (book_root / "output" / "qa_report.md").read_text(encoding="utf-8")
    assert "QA Report" in report_text
    assert "missing_translation" in report_text


def test_run_qa_pass_with_mock_codex_executes_optional_checks(tmp_path: Path) -> None:
    book_root = _prepare_book_root(tmp_path, "book-qa-codex")

    _write_jsonl(
        book_root / "analysis" / "chunks.jsonl",
        [
            {
                "chunk_id": "chunk-1",
                "chapter_id": "chapter-01",
                "page_range": [1, 1],
                "block_ids": ["b1"],
                "chunk_type": "paragraph_group",
                "source_text": "Alpha term remains stable [1].",
                "footnote_refs": [{"marker": "[1]"}],
            }
        ],
    )
    _write_jsonl(
        book_root / "translated" / "translated_chunks.jsonl",
        [
            {
                "chunk_id": "chunk-1",
                "status": "completed",
                "target_text": "Термин Alpha остается стабильным [1].",
            }
        ],
    )

    (book_root / "memory" / "glossary.md").write_text(
        "# Glossary\n\n## Term Table\n| Source term | Target term | POS | Decision | Notes |\n|---|---|---|---|---|\n| Alpha | Альфа | noun | preferred | |\n",
        encoding="utf-8",
    )
    (book_root / "memory" / "style_guide.md").write_text(
        "# Style Guide\n- Keep precise terminology.\n", encoding="utf-8"
    )
    (book_root / "memory" / "chapter_notes.md").write_text(
        "# Chapter Notes\n\n## chapter-01\n- Keep stable terms.\n", encoding="utf-8"
    )

    result = run_qa_pass(
        book_root=book_root,
        options=QAOptions(codex_enabled=True, codex_on_risk_only=False),
        backend=MockCodexBackend(),
    )

    assert result.codex_semantic_jobs == 1
    assert result.codex_terminology_jobs == 1
    assert result.codex_failed_jobs == 0

    codex_jobs = _read_jsonl(book_root / "logs" / "codex_jobs.jsonl")
    stages = {str(item.get("stage", "")) for item in codex_jobs}
    assert "qa_semantic" in stages
    assert "qa_terminology" in stages


def test_qa_command_runs_local_mode_and_writes_outputs() -> None:
    with runner.isolated_filesystem():
        root = Path(".")
        book_root = _prepare_book_root(root, "book-qa-cli")

        _write_jsonl(
            book_root / "analysis" / "chunks.jsonl",
            [
                {
                    "chunk_id": "chunk-1",
                    "chapter_id": "chapter-01",
                    "page_range": [1, 1],
                    "block_ids": ["b1"],
                    "chunk_type": "paragraph_group",
                    "source_text": "Simple line [1].",
                    "footnote_refs": [{"marker": "[1]"}],
                }
            ],
        )
        _write_jsonl(
            book_root / "translated" / "translated_chunks.jsonl",
            [
                {
                    "chunk_id": "chunk-1",
                    "status": "completed",
                    "target_text": "Простая строка [1].",
                }
            ],
        )
        (book_root / "memory" / "glossary.md").write_text("# Glossary\n\n## Term Table\n", encoding="utf-8")
        (book_root / "memory" / "style_guide.md").write_text("# Style Guide\n", encoding="utf-8")
        (book_root / "memory" / "chapter_notes.md").write_text("# Chapter Notes\n", encoding="utf-8")

        result = runner.invoke(app, ["qa", "book-qa-cli"])

        assert result.exit_code == 0
        assert "QA completed" in result.output
        assert (book_root / "translated" / "qa_flags.jsonl").exists()
        assert (book_root / "output" / "qa_report.md").exists()
        assert (book_root / "output" / "translation_summary.md").exists()
        assert (book_root / "logs" / "run.log").exists()


def test_qa_command_runs_codex_mode_with_mock_backend() -> None:
    with runner.isolated_filesystem():
        root = Path(".")
        book_root = _prepare_book_root(root, "book-qa-cli-mock")

        _write_jsonl(
            book_root / "analysis" / "chunks.jsonl",
            [
                {
                    "chunk_id": "chunk-1",
                    "chapter_id": "chapter-01",
                    "page_range": [1, 1],
                    "block_ids": ["b1"],
                    "chunk_type": "paragraph_group",
                    "source_text": "Alpha chunk [1].",
                    "footnote_refs": [{"marker": "[1]"}],
                }
            ],
        )
        _write_jsonl(
            book_root / "translated" / "translated_chunks.jsonl",
            [
                {
                    "chunk_id": "chunk-1",
                    "status": "completed",
                    "target_text": "Альфа чанк [1].",
                }
            ],
        )
        (book_root / "memory" / "glossary.md").write_text(
            "# Glossary\n\n## Term Table\n| Source term | Target term | POS | Decision | Notes |\n|---|---|---|---|---|\n| Alpha | Альфа | noun | preferred | |\n",
            encoding="utf-8",
        )
        (book_root / "memory" / "style_guide.md").write_text("# Style Guide\n", encoding="utf-8")
        (book_root / "memory" / "chapter_notes.md").write_text("# Chapter Notes\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "qa",
                "book-qa-cli-mock",
                "--codex-based",
                "--backend",
                "mock",
                "--codex-on-all",
            ],
        )

        assert result.exit_code == 0
        assert "Codex mode                  : True" in result.output
        assert "Codex semantic jobs" in result.output
        assert (book_root / "logs" / "codex_jobs.jsonl").exists()
