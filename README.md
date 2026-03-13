# GPTtranslate

Linux-first CLI pipeline for translating English books from PDF to Russian PDF while preserving structure as safely as possible.

The project is file-based and resumable:

```text
PDF -> inspect -> extract -> glossary/memory -> translate -> QA -> build
```

## Constraints

- No OpenAI API, SDK, HTTP LLM calls, or API keys.
- The only model-powered backend is an external `codex` CLI subprocess.
- All Codex interaction is file-based: `input.json`, `prompt.md`, `output.json`, `meta.json`, raw stdout/stderr.
- Deterministic local logic is preferred before any Codex call.

## Installation

Requirements:

- Linux
- Python 3.11+
- Internet access for the initial dependency install unless your package cache is already warm

Quick start after `git clone`:

```bash
cd GPTtranslate
./scripts/install.sh
source .venv/bin/activate
gpttranslator --help
```

What `./scripts/install.sh` does:

- prefers `uv` when available
- falls back to `python3 -m venv` + `pip`
- creates a local virtual environment at `.venv/` by default
- installs the package in editable mode
- verifies that the `gpttranslator` console entrypoint was created

Useful install variants:

```bash
./scripts/install.sh --venv-dir /tmp/gpttranslator-venv
./scripts/dev_install.sh
./scripts/uninstall.sh
```

Important:

- `gpttranslator` is available after you activate the virtual environment, or by calling `.venv/bin/gpttranslator` directly.
- By default the CLI uses the current working directory as the project root and writes its workspace to `./workspace/`.
- To run against another root explicitly, set `GPTTRANSLATOR_PROJECT_ROOT=/path/to/project-root`.

## Development Setup

Install dev dependencies:

```bash
./scripts/dev_install.sh
source .venv/bin/activate
```

Make targets:

```bash
make install
make dev-install
make lint
make typecheck
make test
make smoke
make check
```

Direct quality commands:

```bash
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
.venv/bin/python -m pytest -q
```

## Smoke Test

Basic CLI smoke:

```bash
gpttranslator --help
gpttranslator version
gpttranslator status
```

Minimal local pipeline smoke with mock translation backend:

```bash
gpttranslator init /path/to/book.pdf
gpttranslator inspect <book_id>
gpttranslator extract <book_id>
gpttranslator glossary <book_id>
gpttranslator translate <book_id> --backend mock --profile balanced --batch-size 2 --strict-json
gpttranslator qa <book_id> --local-only
gpttranslator build <book_id>
gpttranslator status <book_id>
```

Build a wheel locally:

```bash
python3 -m pip wheel . --no-build-isolation --no-deps -w dist
```

## CLI Commands

- `gpttranslator help`
- `gpttranslator status [book_id]`
- `gpttranslator init <path-to-pdf>`
- `gpttranslator inspect <book_id>`
- `gpttranslator extract <book_id> [--ocr-mode off|auto|force] [--ocr-language eng] [--ocr-dpi 200]`
- `gpttranslator glossary <book_id> [--find <term>]`
- `gpttranslator budget <book_id>`
- `gpttranslator translate <book_id> [--profile economy|balanced|quality] [--backend codex-cli|mock] [--dry-run] [--resume]`
- `gpttranslator qa <book_id> [--codex-based --backend codex-cli|mock]`
- `gpttranslator build <book_id> [--prefer-edited] [--fallback-mode conservative|aggressive-reflow]`
- `gpttranslator version`

## Workspace Layout

Each book lives under `workspace/<book_id>/`:

```text
workspace/
├── state.json
└── <book_id>/
    ├── manifest.json
    ├── input/
    │   └── original.pdf
    ├── analysis/
    │   ├── inspection_report.json
    │   ├── pages.jsonl
    │   ├── blocks.jsonl
    │   ├── images.jsonl
    │   ├── footnotes.jsonl
    │   ├── sections.jsonl
    │   ├── document_graph.json
    │   └── chunks.jsonl
    ├── memory/
    │   ├── glossary.md
    │   ├── style_guide.md
    │   ├── chapter_notes.md
    │   └── translation_memory.jsonl
    ├── translated/
    ├── output/
    ├── logs/
    └── jobs/
```

Key properties:

- resumable runs via local artifacts and checkpoints
- no silent overwrite of core artifacts by install flow
- explicit logs for stage transitions and Codex job failures

## Codex Job Contract

Each job uses:

```text
workspace/<book_id>/jobs/<job_id>/
├── input.json
├── prompt.md
├── output.json
├── meta.json
├── raw_stdout.txt
└── raw_stderr.txt
```

Schema versions:

- `gpttranslator.codex.input.v1`
- `gpttranslator.codex.prompt_template.v1`
- `gpttranslator.codex.output.v1`
- `gpttranslator.codex.meta.v1`

Prompt templates are available both in the repository `prompts/` directory and in packaged prompt assets, so installed builds do not depend on the source tree being present.

## How To Verify Codex Availability

Basic shell checks:

```bash
command -v codex
codex --help
```

If `codex` is installed under a non-default name or path:

```bash
GPTTRANSLATOR_CODEX_COMMAND=/path/to/codex gpttranslator translate <book_id> --backend codex-cli
```

Expected failure behavior when Codex is missing:

- the CLI exits with a clear error
- no fake translation is reported as success
- workspace artifacts already produced by earlier deterministic stages remain intact
- no new `jobs/` directory is created before backend availability is confirmed

## Quality Gates

Current repo checks:

- `pytest`
- `ruff`
- `mypy`
- installed-entrypoint smoke via `scripts/install.sh`
- wheel build smoke via `python3 -m pip wheel . --no-build-isolation --no-deps`

Mock-mode coverage exists for:

- CLI smoke
- init / inspect / extract
- glossary management
- translation batching and resume
- missing-Codex failure path
- QA
- build
- end-to-end pipeline smoke on fixture PDFs

## Known Limitations

- Real translation quality with the actual `codex` CLI depends on the local Codex installation and login state; this repository does not bundle Codex itself.
- Installation is virtualenv-based by default. The project does not pretend that `gpttranslator` is globally available without activation or PATH changes.
- PDF rebuild is controlled reflow, not guaranteed in-place layout replacement for arbitrary PDFs.
- OCR is local and conservative. Embedded text inside images, chart relabeling, and formula reconstruction are not implemented as general features in v1.
- The current version uses model-powered execution only for translation/editorial and optional Codex QA paths. Glossary generation, chapter summarization, and orchestration stay deterministic/local in normal operation.

## Notes For Long Books

For 300-500+ page books:

- run `budget` before `translate`
- prefer `--profile economy` or `--profile balanced`
- keep `--tm-first` and `--reuse-cache` enabled
- use `--resume` and `--only-failed` for interrupted runs
- avoid full Codex QA on every chunk unless there is a specific reason
