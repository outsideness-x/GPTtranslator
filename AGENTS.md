# AGENTS.md — GPTtranslator

## Project purpose

GPTtranslator is a Linux-first CLI application for translating English books from PDF to Russian PDF while preserving document structure as reliably as possible.

The system is designed as a file-based pipeline:

PDF -> inspection -> extraction -> document model -> chunking -> glossary/memory -> translation -> editorial pass -> QA -> PDF rebuild

The app must support long books, including 300–500+ pages, and must be resumable, testable, and production-friendly.

---

## Hard architecture constraints

1. Do not use OpenAI API, Responses API, Chat Completions API, SDK clients, HTTP calls to LLMs, or any API keys.
2. The only model-powered mechanism allowed in this project is an external shell/subprocess call to installed `codex` CLI.
3. Assume the user is already authenticated in Codex CLI via ChatGPT account.
4. All model interactions must be file-based:
   - prepare input JSON
   - prepare prompt file
   - call `codex`
   - read structured output from file
5. Prefer deterministic local processing wherever possible.
6. Never introduce network-dependent translation backends.
7. Keep the architecture backend-aware but with only one real backend: `CodexCliBackend`.

---

## Engineering priorities

Optimize for these, in order:

1. Structural integrity
2. Footnote preservation
3. Terminology consistency
4. Resume/retry robustness
5. Deterministic local processing
6. Economy of Codex usage
7. Readable, maintainable Python code

Do not sacrifice footnote markers, chunk identity, or output schema correctness for convenience.

---

## Scope of the product

The product is a CLI pipeline, not a GUI, not a web service, and not a TUI-heavy app.

Primary commands are expected to include:

- `init`
- `status`
- `inspect`
- `extract`
- `glossary`
- `translate`
- `qa`
- `build`
- `budget`

Keep output clean, compact, and terminal-friendly.

---

## Repository expectations

Expected top-level structure:

- `app/commands`
- `app/core`
- `app/pdf`
- `app/translation`
- `app/qa`
- `app/render`
- `app/utils`
- `prompts/`
- `workspace/`
- `tests/`

Do not collapse the project into one or two large files.

Keep command registration separated from implementation logic.

---

## Python standards

1. Use Python with type hints throughout.
2. Prefer small focused modules.
3. Prefer dataclasses or Pydantic models for structured entities.
4. Avoid hidden global state.
5. Prefer explicit file paths and explicit state transitions.
6. Write code that is easy to test with local fixtures.
7. Avoid unnecessary dependencies.
8. Keep Linux compatibility first.

---

## Data model expectations

Core entities should remain explicit and stable:

- `BookManifest`
- `PageInfo`
- `Block`
- `Chunk`
- `TranslationRecord`
- `QAFlag`
- `CodexJob`
- `CodexResult`

Artifacts should be stored in JSON, JSONL, and Markdown.

Do not invent opaque binary intermediate formats unless there is a strong reason.

---

## Workspace rules

For each book, create a dedicated workspace such as:

`workspace/<book_id>/`

Expected directories:

- `input/`
- `analysis/`
- `memory/`
- `translated/`
- `output/`
- `logs/`
- `jobs/` if codex jobs are materialized per task

The workspace must be resumable. Never assume a single uninterrupted run.

Do not overwrite important artifacts silently.

---

## Translation pipeline rules

### Before calling Codex

Always prefer local logic first:

1. exact translation memory hit
2. near-exact translation memory reuse if safe
3. glossary retrieval
4. local heuristics / deterministic transformation
5. only then call `codex`

Never call Codex for:
- empty text
- page numbers
- trivial repeated headers/footers
- exact duplicate already-approved segments
- obviously non-translatable boilerplate when local reuse is sufficient

### When calling Codex

Every Codex job must be file-based and traceable.

Each job should have a dedicated directory with at least:

- `input.json`
- `prompt.md`
- `output.json`
- `meta.json`
- `raw_stdout.txt`
- `raw_stderr.txt`

Do not rely only on parsing free-form stdout.

Require strict structured output.

If the output is invalid:
- keep raw artifacts
- log the failure
- retry conservatively
- prefer a repair-mode prompt over a blind full rerun

---

## Prompting rules for Codex

Prompts must be:

- compact
- explicit
- schema-driven
- reproducible

They must:

1. preserve `chunk_id`
2. preserve block references
3. preserve footnote markers
4. respect glossary and style rules
5. return strict JSON only when a structured file is expected
6. avoid unnecessary reasoning verbosity

Do not inject the entire glossary or full chapter notes into every job.
Use minimal relevant context only.

---

## Economy rules

This project must be cost-aware and limit-aware.

Always try to reduce Codex load without lowering translation quality materially.

Preferred strategy:

- adaptive chunking
- glossary slicing
- translation-memory-first
- selective editorial pass
- selective Codex-based QA only on risky chunks
- deduplication of identical jobs
- cache valid results by content fingerprint

Do not run editorial pass on every chunk by default.
Do not run semantic QA on every chunk by default.

---

## PDF and structure rules

Do not treat PDF translation as plain text replacement.

Preferred approach:

PDF -> structured extraction -> translated text blocks -> controlled rebuild/reflow

Important:
- preserve image assets
- preserve captions
- preserve footnote links
- preserve reading order as reliably as possible
- mark low-confidence extraction explicitly

Do not promise perfect in-place layout replacement for all PDFs.
Use controlled rebuild/reflow when necessary.

---

## OCR rules

OCR is a separate branch, not the default.

If a PDF is likely scanned:
- mark it clearly
- use OCR pipeline explicitly
- record confidence scores
- surface low-confidence pages and blocks
- make QA stricter

Do not hide OCR uncertainty.

---

## QA rules

QA must have a local deterministic layer first.

Always check locally for:
- missing chunk outputs
- empty translations
- footnote marker mismatch
- suspicious loss of numbers/dates/links
- schema failures
- duplicate or missing IDs

Codex-based QA should be optional and risk-triggered.

Save QA artifacts explicitly.

---

## Testing rules

When making changes:

1. update or add tests
2. prefer unit tests first
3. add smoke or integration tests where appropriate
4. do not leave untested orchestration code if it can be tested locally with mocks

The project should support tests that run without real Codex calls by using a mock backend.

---

## CLI behavior rules

Keep the CLI minimal and stable.

Requirements:
- concise terminal output
- clear errors
- no noisy decorative logging
- predictable exit codes
- commands should not surprise the user with hidden stages

Do not automatically launch unrelated heavy stages unless explicitly requested.

Example:
`translate` should not silently run full `build` unless designed and documented to do so.

---

## Logging and observability

Log enough to debug failures, especially around Codex subprocess jobs.

At minimum capture:
- stage start/end
- manifest transitions
- job IDs
- retry reasons
- output validation failures
- cache hits
- translation memory reuse
- skipped Codex calls
- batch progress

Logs should be useful during resume and postmortem.

---

## Safe change policy

Before making structural changes:

1. understand the existing module boundaries
2. preserve public CLI behavior unless the task explicitly changes it
3. avoid unnecessary renames
4. do not break workspace compatibility without migration logic
5. update README if behavior changes
6. prefer incremental patches over broad rewrites

Do not refactor the whole repository unless explicitly asked.

---

## Delivery expectations for each task

When implementing a task:

1. explain briefly what will change
2. make the code changes
3. keep file structure clean
4. update tests
5. show how to run the relevant command/test
6. mention any assumptions or limitations honestly

If something is not implemented, say so clearly instead of faking completeness.

---

## What success looks like

A good change in this repo usually has these properties:

- minimal but complete
- testable
- resumable
- file-based
- robust to Codex failures
- parsimonious with Codex usage
- preserves document structure and translation integrity
- does not introduce API dependencies

## Translation-specific rules

### General translation goal

The translation subsystem must produce Russian text that is:

- faithful to the source meaning
- terminologically consistent across the whole book
- structurally aligned with the source document model
- suitable for editorial-quality post-processing
- safe for long-book batch execution and resume

Do not optimize for flashy prose at the cost of accuracy.
Do not optimize for literalness when it clearly damages meaning in Russian.
Prefer stable, controlled, reproducible translation behavior.

---

### Source of truth for translation decisions

When translating a chunk, use this priority order:

1. explicit project glossary
2. approved translation memory entry
3. chapter notes
4. style guide
5. local source context
6. broader section/chapter context
7. Codex judgment only where no approved project rule exists

If glossary and free interpretation conflict, glossary wins unless there is a clear error in glossary data.
If translation memory contains an approved exact match, reuse it instead of creating a fresh translation.

---

### Required invariants

Every translation job must preserve:

- `chunk_id`
- `block_ids` or equivalent source references
- footnote markers
- ordering of block-level meaning
- paragraph boundaries when they matter structurally
- list structure
- caption association
- named entities unless a glossary-approved Russian form exists

Do not silently drop:
- footnote calls
- numbers
- dates
- references
- emphasis-bearing quoted fragments
- parenthetical qualifications
- section labels
- repeated key terms

---

### Footnotes and note markers

Footnote markers are critical and must never be lost.

Rules:
- preserve every source footnote marker
- preserve marker count
- preserve marker-to-note linkage whenever the model receives such linkage
- do not merge or delete notes for stylistic reasons
- do not move note content into body text unless explicitly instructed by pipeline logic
- if source note attachment is ambiguous, keep the marker and flag uncertainty rather than guessing silently

If a chunk contains both body text and note text, keep them separable in output data.

---

### Terminology rules

Terminology consistency is one of the highest priorities.

Rules:
- use glossary-approved term translations exactly unless a controlled override is explicitly requested
- prefer one approved Russian term per source term per book or per domain sense
- distinguish true term variation from accidental inconsistency
- track polysemy by context where needed
- do not improvise synonyms for core technical or philosophical terms
- do not alternate between different Russian renderings of the same source term for stylistic variety

If a term is ambiguous:
- choose the sense supported by local context
- record uncertainty if the system supports it
- prefer consistency within the same chapter and semantic domain

---

### Named entities and titles

Rules:
- preserve personal names consistently
- use glossary-approved transliteration or accepted Russian form
- do not retranslate the same proper noun differently in later chunks
- preserve book, article, institutional, and organization names according to project rules
- if a title is already translated in project memory, reuse the approved form
- do not invent unofficial Russian titles unless the workflow explicitly allows it

---

### Style rules for Russian output

Russian output must be natural and readable, but controlled.

Rules:
- prefer clear literary Russian over mechanical calque
- preserve register of the source: academic, literary, popular science, technical, formal, conversational
- avoid needless verbosity
- avoid flattening distinctions in argument structure
- preserve authorial nuance where possible
- do not simplify complex passages unless simplification is explicitly requested
- follow project punctuation and quotation rules from `style_guide.md`

Do not make the translation “more beautiful” if that weakens precision.

---

### Literalness vs readability

Use the following default policy:

- preserve meaning first
- preserve argument structure second
- preserve tone/register third
- preserve sentence shape only where it does not damage Russian readability

Allowed:
- syntactic restructuring for natural Russian
- splitting very heavy English sentences if meaning and structure remain intact
- modest reordering for clarity

Not allowed:
- adding new interpretation
- deleting hedges, qualifiers, or uncertainty
- collapsing distinctions between related but different claims
- replacing a precise technical term with a vague paraphrase

---

### Local context usage

When translating a chunk, use only the minimum context needed for quality.

Relevant context may include:
- previous and next chunks
- chapter summary
- glossary subset
- translation memory matches
- section title
- note relationships

Do not require the entire book context for routine chunks.
Do not inject large irrelevant context into translation jobs.

---

### Translation memory usage

Translation memory is mandatory when useful.

Rules:
- exact match -> reuse directly
- near-exact match -> reuse carefully if semantics align
- repeated boilerplate -> prefer memory or deterministic reuse
- repeated headings/captions -> reuse approved translations when identical

If reusing memory:
- preserve local IDs and structural metadata
- ensure reused translation fits the current grammatical environment
- do not reuse blindly when a source segment is only superficially similar

---

### Chunk handling rules

Different chunk types require different behavior.

#### Prose paragraphs
- translate semantically and naturally
- preserve rhetorical structure
- preserve explicit contrast, causality, and qualification

#### Headings
- keep concise
- preserve hierarchy and tone
- do not over-explain

#### Captions
- preserve linkage to image
- keep concise and informative
- preserve numbering and labels

#### Footnotes
- preserve note logic and marker linkage
- keep scholarly or editorial tone where relevant
- do not normalize away source-specific detail

#### Lists
- preserve item structure
- preserve numbering and bullets
- keep parallelism where present

---

### Ambiguity handling

If a source passage is ambiguous:

- do not silently over-resolve ambiguity
- prefer the reading best supported by immediate context
- preserve ambiguity when it appears intentional
- flag uncertainty in metadata if the output schema supports flags
- do not invent explanatory additions in the main translation

When ambiguity materially affects terminology, prefer the glossary or chapter-level precedent.

---

### Output requirements for model-powered translation

Whenever Codex is used for translation, output must be:

- schema-compliant
- chunk-scoped
- free of extra commentary
- consistent with requested JSON contract
- explicit about any uncertainty if the schema includes such fields

Never return free-form essays when a structured translation output is required.

---

### Economy and quality balance

Translation should be cost-aware without harming core quality.

Rules:
- do not call Codex for exact translation memory matches
- do not call Codex for empty or trivial non-translatable content
- do not run editorial pass on every chunk by default
- do not run semantic QA on every chunk by default
- reserve heavier passes for risky or complex chunks

Never save usage by sacrificing:
- footnote integrity
- terminology consistency
- structural correctness
- chunk traceability

---

### Forbidden behaviors

The translation subsystem must not:

- invent missing source content
- drop note markers
- silently omit hard sentences
- paraphrase technical content into vagueness
- vary core terms for style
- merge separate claims into one
- output unstructured text when structured output is required
- overwrite approved glossary decisions without explicit reason
- hide uncertainty when extraction/source linkage is weak

---

### Preferred failure behavior

If translation quality is doubtful, prefer controlled failure over silent corruption.

That means:
- preserve raw artifacts
- emit a validation or QA flag
- allow retry with smaller chunk or richer local context
- keep the pipeline resumable
- make the failure inspectable in logs and job artifacts