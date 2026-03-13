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
- `translate <book_id>` runs a production-style economy planner with adaptive chunking, TM-first routing, tiering, selective editorial/QA planning, and savings observability artifacts.
- `translate` runs chunk/batch execution with resume/checkpoints and supports `--backend`, `--dry-run`, `--batch-size`, `--resume`, `--only-failed`, `--strict-json`.
- After translation batches, command runs:
  - Codex editorial pass -> `translated/edited_chunks.jsonl`
  - deterministic consistency pass -> `translated/consistency_flags.jsonl`
- `budget <book_id>` estimates Codex pressure heuristically without token APIs.
- `qa <book_id>` runs local deterministic checks and can optionally run Codex semantic/terminology QA with `--codex-based`.
- `build <book_id>` assembles local `output/translated_book.pdf` and `output/build_report.md` from translated data and extraction artifacts.
- Build typesetting supports deterministic reflow controls:
  - line wrapping and page breaks
  - widow/orphan handling
  - page-level footnote area policy
  - caption proximity handling for image-related overflow
  - multi-page block continuation
- Codex runtime protocol contract is implemented as file-based job artifacts + strict output validation + retry/recovery policy.

## Final project structure

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
│   │   ├── budget.py
│   │   ├── translate.py
│   │   ├── qa.py
│   │   └── build.py
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── paths.py
│   │   ├── models.py
│   │   ├── manifest.py
│   │   ├── reporting.py
│   │   └── state.py
│   ├── memory/
│   │   ├── glossary_manager.py
│   │   ├── style_guide_manager.py
│   │   └── translation_memory_manager.py
│   ├── pdf/
│   │   ├── ingestion.py
│   │   ├── inspector.py
│   │   ├── extractor.py
│   │   ├── document_graph.py
│   │   └── ocr.py
│   ├── translation/
│   │   ├── protocol.py
│   │   ├── codex_backend.py
│   │   ├── economy/
│   │   │   ├── profiles.py
│   │   │   ├── adaptive.py
│   │   │   ├── context.py
│   │   │   ├── prefilter.py
│   │   │   ├── planner.py
│   │   │   ├── dedupe.py
│   │   │   ├── retry.py
│   │   │   ├── budget.py
│   │   │   └── service.py
│   │   └── backends/
│   │       ├── base.py
│   │       └── codex_cli.py
│   ├── qa/
│   │   └── service.py
│   ├── render/
│   │   ├── assets.py
│   │   ├── composer.py
│   │   ├── pdf_writer.py
│   │   ├── service.py
│   │   └── typesetter.py
│   └── utils/
├── cli.py
├── __main__.py
├── prompts/
├── tests/
│   ├── fixtures/
│   │   ├── codex_job_example/
│   │   ├── mock_codex_cli.py
│   │   └── pdfs/
│   │       ├── text_fixture.pdf
│   │       └── scan_fixture.pdf
│   └── test_*.py
└── workspace/
```

## CLI commands

- `help`
- `status [book_id]`
- `init <path-to-pdf>`
- `inspect <book_id>`
- `extract <book_id> [--ocr-mode off|auto|force] [--ocr-language eng] [--ocr-dpi 200]`
- `glossary <book_id> [--find <term>]`
- `budget <book_id>`
- `translate <book_id> [--profile ...] [--backend codex-cli|mock] [--dry-run] [--resume]`
- `qa <book_id> [--codex-based --backend codex-cli|mock]`
- `build <book_id> [--prefer-edited] [--fallback-mode conservative|aggressive-reflow] [--font-scale-min N] [--font-scale-max N] [--line-spacing N] [--page-margin-* N] [--footnote-area-policy reserve|adaptive|ignore] [--reflow-page-char-budget N]`
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

## Economy profiles

Profiles tune chunking, context size, optional passes, and retries:

- `economy`
  - larger chunks, smaller context package
  - editorial and Codex QA mostly disabled
  - minimal retries, strict recovery behavior
- `balanced` (default for most books)
  - moderate chunk size and context
  - selective editorial and risk-only QA
  - conservative retries
- `quality`
  - smaller chunks, richer context
  - more editorial and QA coverage
  - higher retry budget

Default selection:

- normal books -> `balanced`
- very long books (roughly 450+ pages) -> `economy`
- explicit CLI override -> `--profile economy|balanced|quality`

## Cost-aware pipeline components

`translate` and `budget` use deterministic local logic before any Codex work:

- TM-first (`exact` then `near-exact`)
- local pre-filter for empty/non-translatable/repeated fragments
- glossary slicing (exact + fuzzy + chapter decisions)
- compact style/chapter context package
- complexity scoring + tier routing (A/B/C)
- selective editorial / selective QA planning
- job dedup fingerprint + output cache reuse
- retry economy directives
- chapter-level budget estimator and session-pressure warning

Artifacts written per run:

- `workspace/<book_id>/translated/economy_plan.json`
- `workspace/<book_id>/logs/economy_summary.json`
- `workspace/<book_id>/logs/budget_estimate.json`
- `workspace/<book_id>/translated/batch_manifest.json`
- `workspace/<book_id>/translated/chunk_checkpoints.json`
- `workspace/<book_id>/translated/translated_chunks.jsonl`
- `workspace/<book_id>/logs/codex_jobs.jsonl`
- `workspace/<book_id>/logs/codex_failures.jsonl`
- `workspace/<book_id>/translated/edited_chunks.jsonl`
- `workspace/<book_id>/translated/consistency_flags.jsonl`
- `workspace/<book_id>/translated/qa_flags.jsonl`
- `workspace/<book_id>/output/qa_report.md`
- `workspace/<book_id>/output/build_report.md`
- `workspace/<book_id>/output/translation_summary.md`
- `workspace/<book_id>/logs/run.log`

## Prompt templates by stage

- `translate` stage:
  - `translate_chunk` -> `prompts/translate_chunk.prompt.md`
  - `editorial_pass` -> `prompts/editorial_pass.prompt.md` (selective post-pass on risky chunks)
- `qa` stage:
  - `terminology_check` -> `prompts/terminology_check.prompt.md`
  - `semantic_qa` -> `prompts/semantic_qa.prompt.md`
- `memory` / chapter analysis stage:
  - `chapter_summary` -> `prompts/chapter_summary.prompt.md`
- `glossary` stage:
  - `glossary_update_proposal` -> `prompts/glossary_update_proposal.prompt.md`

Prompt rendering is implemented in `gpttranslator.app.translation.protocol.render_prompt()` using the file-based protocol payload (`input.json` + strict output schema).

## Developer setup

```bash
./bin/pip install -e '.[dev]'
```

Codex CLI login (one-time for real backend runs):

```bash
codex --help
# then run codex and complete interactive login
codex
```

Task runner:

```bash
make dev-install
make format
make lint
make typecheck
make test
make test-smoke
make check
```

## Formatting, linting, type checks

```bash
./bin/python -m ruff format src tests
./bin/python -m ruff check src tests
./bin/python -m mypy src
./bin/python -m pytest -q
```

## Integration smoke in mock mode

All integration tests can run without real `codex` calls:

```bash
./bin/python -m pytest -q tests/test_integration_smoke_pipeline.py
```

## Manual run commands

```bash
./bin/pip install -e '.[dev]'
./bin/gpttranslator --help
./bin/gpttranslator init /path/to/book.pdf
./bin/gpttranslator inspect <book_id>
./bin/gpttranslator extract <book_id>
./bin/gpttranslator budget <book_id> --profile balanced
./bin/gpttranslator translate <book_id> --profile economy --qa-on-risk-only --reuse-cache
./bin/gpttranslator translate <book_id> --backend codex-cli --dry-run
./bin/gpttranslator translate <book_id> --resume --only-failed --batch-size 16 --strict-json --strict-terminology --editorial-rewrite-level medium
./bin/gpttranslator qa <book_id> --local-only
./bin/gpttranslator qa <book_id> --codex-based --backend codex-cli --codex-on-risk-only
./bin/gpttranslator build <book_id> --prefer-edited
./bin/gpttranslator build <book_id> --fallback-mode aggressive-reflow --line-spacing 1.25 --footnote-area-policy reserve
./bin/gpttranslator status <book_id>
```

## Recommended long-book workflow (300+ pages)

1. Run `extract` and verify chunk/graph artifacts first.
2. Start with `budget`:
   - `./bin/gpttranslator budget <book_id> --profile economy --adaptive-chunking`
3. Use `translate` in economy/balanced mode with reuse enabled:
   - `./bin/gpttranslator translate <book_id> --profile economy --tm-first --reuse-cache --qa-on-risk-only`
4. Avoid full editorial+semantic QA on every chunk for long books.
5. Split very large books into chapter batches if budget warns about high session pressure.

Recommended flags for savings:

- `--profile economy` for very long or test runs
- `--tm-first`
- `--reuse-cache`
- `--qa-on-risk-only`
- `--adaptive-chunking`
- `--no-editorial` for exploratory drafts

Batch/resume flags for long books:

- `--resume` to continue interrupted runs
- `--only-failed` to re-run only failed batches
- `--from-batch <batch_id>` and `--to-batch <batch_id>` for bounded reruns
- `--batch-size <N>` to constrain per-batch chunk count
- `--strict-json` (or `--best-effort-json`) for strict schema behavior
- `--strict-terminology`, `--preserve-literalness`, `--editorial-rewrite-level light|medium|aggressive` for editorial/consistency behavior

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
