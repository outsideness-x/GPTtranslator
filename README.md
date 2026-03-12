# GPTtranslate

Minimalist terminal CLI shell and production-style project skeleton for a future PDF-to-PDF book translation pipeline.

## Architectural constraints

- No API and no SDK integrations.
- Future LLM backend is only external `codex` CLI shell-out.
- Orchestration is file-based (workspace folders + manifests + job/result artifacts).

## Current stage scope

- CLI is scaffolded and stable.
- `init` performs local ingestion of source PDF into a per-book workspace.
- `inspect` performs fully local PDF inspection and writes JSON report.
- `extract` performs fully local structure extraction and writes JSONL artifacts.
- `extract` now also builds a linked `document_graph` with sections and entity relations.
- `glossary <book_id>` manages local memory assets (`glossary.md`, `style_guide.md`, `chapter_notes.md`, `translation_memory.jsonl`).
- Pipeline services (`translate`, `qa`, `build`) are still CLI stubs.
- Codex runtime protocol contract is implemented as file-based job artifacts + strict output validation + retry/recovery policy.

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
│   ├── memory/
│   │   ├── glossary_manager.py
│   │   ├── style_guide_manager.py
│   │   └── translation_memory_manager.py
│   ├── pdf/
│   │   ├── ingestion.py
│   │   ├── inspector.py
│   │   ├── extractor.py
│   │   └── document_graph.py
│   ├── translation/
│   │   ├── protocol.py
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
- `inspect <book_id>`
- `extract <book_id>`
- `glossary <book_id> [--find <term>]`
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
    │   ├── inspection_report.json   # created by `inspect`
    │   ├── pages.jsonl              # created by `extract`
    │   ├── blocks.jsonl             # created by `extract`
    │   ├── images.jsonl             # created by `extract`
    │   ├── sections.jsonl           # created by `extract`
    │   ├── footnotes.jsonl          # created by `extract`
    │   └── document_graph.json      # created by `extract`
    ├── memory/
    │   ├── glossary.md
    │   ├── style_guide.md
    │   ├── chapter_notes.md
    │   └── translation_memory.jsonl
    ├── translated/
    ├── output/
    └── logs/
```

## Codex job file contract

Each Codex job lives under:

```text
workspace/<book_id>/jobs/<job_id>/
├── input.json
├── prompt.md
├── output.json
├── raw_stdout.txt
├── raw_stderr.txt
└── meta.json
```

Contract schema versions:

- `input.json`: `gpttranslator.codex.input.v1`
- `prompt.md` template payload schema: `gpttranslator.codex.prompt_template.v1`
- `output.json`: `gpttranslator.codex.output.v1` (strict validation, extra fields rejected)
- `meta.json`: `gpttranslator.codex.meta.v1`

Recovery policy in `codex_cli` backend:

- `invalid_json` -> retry
- `partial_json` -> retry
- `timeout` -> retry
- `interrupted_process` -> retry
- `missing_output_file` -> retry
- `output_schema_validation_failed` -> retry

No translation content is parsed from stdout/stderr. Only `output.json` is considered authoritative.

## Install and run

```bash
./bin/pip install -e '.[dev]'
./bin/gpttranslator --help
./bin/gpttranslator init /path/to/book.pdf
./bin/gpttranslator inspect <book_id>
./bin/gpttranslator extract <book_id>
./bin/gpttranslator status
```

## Extraction JSONL schema

`analysis/blocks.jsonl` row:

- `block_id`
- `page_num`
- `block_type` (`heading`, `paragraph`, `caption`, `footnote_marker`, `footnote_body`, `image_anchor`, `header`, `footer`)
- `bbox` (`[x0, y0, x1, y1]` or `null`)
- `reading_order`
- `text`
- `style_metadata` (font metrics + confidence + optional image metadata)
- `flags` (heuristic warnings including low-confidence tags)

`analysis/document_graph.json` includes relations:

- `footnote_link`: marker block -> footnote body block (with confidence)
- `caption_image`: caption block -> image asset (with confidence)
- `block_section`: block -> section/chapter
- `adjacent`: block -> next block in reading flow

## Tests

```bash
./bin/python -m pytest
```
