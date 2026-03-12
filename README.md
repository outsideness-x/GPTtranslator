# GPTtranslate

Minimalist terminal CLI shell and production-style project skeleton for a future PDF-to-PDF book translation pipeline.

## Architectural constraints

- No API and no SDK integrations.
- Future LLM backend is only external `codex` CLI shell-out.
- Orchestration is file-based (workspace folders + manifests + job/result artifacts).

## Current stage scope

- CLI is scaffolded and stable.
- `init` performs local ingestion of source PDF into a per-book workspace.
- Pipeline services (`inspect`, `extract`, `translate`, `qa`, `build`) are stubs.
- `codex` runtime execution is intentionally not implemented yet.

## Architecture

```text
src/gpttranslator/
├── app/
│   ├── cli_app.py
│   ├── commands/
│   │   ├── registry.py
│   │   ├── help.py
│   │   ├── status.py
│   │   ├── init.py
│   │   ├── inspect.py
│   │   ├── extract.py
│   │   ├── glossary.py
│   │   ├── translate.py
│   │   ├── qa.py
│   │   └── build.py
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── paths.py
│   │   ├── models.py
│   │   ├── manifest.py
│   │   └── state.py
│   ├── pdf/
│   │   └── ingestion.py
│   ├── translation/
│   │   └── backends/
│   │       ├── base.py
│   │       └── codex_cli.py
│   ├── qa/
│   ├── render/
│   └── utils/
├── cli.py
└── __main__.py

prompts/
workspace/
```

## CLI commands

- `help`
- `status`
- `init <path-to-pdf>`
- `inspect`
- `extract`
- `glossary`
- `translate`
- `qa`
- `build`
- `version`

## Init workspace layout

Command:

```bash
gpttranslator init /path/to/book.pdf
```

Resulting structure:

```text
workspace/
├── state.json
└── <book_id>/
    ├── manifest.json
    ├── input/
    │   └── original.pdf
    ├── analysis/
    ├── memory/
    │   ├── glossary.md
    │   ├── style_guide.md
    │   ├── chapter_notes.md
    │   └── translation_memory.jsonl
    ├── translated/
    ├── output/
    └── logs/
```

## Install and run

```bash
./bin/pip install -e '.[dev]'
./bin/gpttranslator --help
./bin/gpttranslator init /path/to/book.pdf
./bin/gpttranslator status
```

## Tests

```bash
./bin/python -m pytest
```
