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

## Current version translation policy

In the current project version, Codex CLI is used only for chunk-level translation.

Codex must not be used yet for:
- glossary generation
- chapter summarization
- semantic QA
- editorial rewriting
- terminology arbitration
- document planning
- pipeline control

All orchestration, extraction, chunking, caching, resume, validation, and PDF build must be implemented as deterministic local logic.

Optional model-powered passes may be added later as explicitly separated features.

## Image and formula preservation rules

### General rule

In the current project version, images, formulas, diagrams, tables-as-graphics, and other non-prose visual objects are not treated as ordinary translatable text.

The default policy is:

- translate text blocks
- preserve visual assets
- rebuild layout around them
- do not let the model rewrite or reinterpret visual/math content unless a separate specialized workflow explicitly exists

---

### Asset categories

Treat the following as distinct asset classes:

- raster images
- vector illustrations
- scanned page regions
- display formulas
- inline math spans
- tables
- charts
- figure labels and captions
- decorative or structural page elements

Do not merge these into a single generic “block” without preserving type information.

---

### What must be translated

Translate only where translation is actually required:

- prose paragraphs
- headings
- captions
- footnotes
- endnotes
- figure references in body text
- textual labels that are already extracted as true text blocks

---

### What must be preserved as-is by default

Preserve as original assets by default:

- photographs
- illustrations
- charts as images
- diagrams as images
- scanned figure regions
- display equations
- equation numbering
- inline mathematical notation
- tables that cannot be safely reconstructed as structured tables
- symbols, operators, notation, and variable names

Do not send these objects to the translation model unless a dedicated specialized stage is explicitly added.

---

### Images

Rules for images:

- extract image assets separately from prose
- preserve image identity, page origin, and bounding box
- maintain image-to-caption linkage
- reinsert original image assets into the rebuilt PDF
- keep images as immutable layout objects unless resizing is required for controlled reflow

Do not regenerate or reinterpret images.
Do not ask the model to describe images unless a separate accessibility/export feature is requested.
Do not modify figure content in v1.

If an image contains embedded text, treat that as a separate future feature unless the embedded text was already extracted as real text blocks.

---

### Captions

Captions are translatable text, but they remain structurally tied to their asset.

Rules:
- preserve caption-to-image linkage
- preserve figure numbering
- preserve caption order
- keep caption text near its related asset in rebuilt layout
- if reflow requires moving the image, move its caption with it

Do not detach captions from figures.
Do not merge multiple captions unless the source explicitly does so.

---

### Formulas

Formulas are high-risk content and must be preserved conservatively.

Default policy:
- preserve formulas as-is
- translate surrounding prose only
- preserve formula numbering
- preserve references such as “Eq. (3.2)” semantically while keeping the number unchanged

Do not paraphrase math content.
Do not rewrite notation for style.
Do not replace equations with descriptive text.
Do not let the model “improve” formulas.

---

### Display formulas

For standalone equations or displayed formulas:

- detect and store them as equation blocks or visual assets
- preserve exact ordering within the page/section
- preserve numbering labels such as `(1.2)`, `(3.7)`, etc.
- reinsert them into the rebuilt PDF as dedicated layout objects

If native equation reconstruction is not reliable, preserve the formula region as a visual asset rather than risking corruption.

Controlled preservation is preferred over incorrect regeneration.

---

### Inline math

Inline math should remain intact inside translated text.

Rules:
- protect inline formulas before translation
- keep variables, symbols, operators, and notation unchanged
- translate only surrounding natural language
- restore inline math exactly after translation
- preserve spacing and punctuation rules as safely as possible

Do not allow the translation model to alter symbols, variable names, or mathematical relations unless explicitly instructed by a specialized math-aware module.

---

### Tables

Tables require separate handling.

Rules:
- if a table is extracted as structured text reliably, it may be reconstructed as a table
- if extraction is unreliable, preserve the table region as an asset
- preserve table numbering and captions
- preserve table-to-reference linkage in body text

Do not flatten tables into prose by default.
Do not trust weak extraction for complex scientific or financial tables.

---

### Charts and diagrams

Charts and diagrams should be preserved as assets in v1.

Rules:
- preserve the visual object
- translate only surrounding caption/reference text
- do not rebuild chart internals unless a specialized chart-text workflow exists
- do not let the translation model infer or redraw labels from visual appearance alone

If chart labels are already extracted as text with reliable coordinates, keep them separable and explicitly marked.

---

### Layout behavior for preserved assets

Preserved assets must behave as layout anchors.

Rules:
- treat images and formulas as non-fragmentable blocks unless a specialized rule exists
- if surrounding Russian text expands, prefer moving the asset as a unit rather than distorting it
- keep captions attached to their asset
- preserve reading order around the asset
- prefer controlled reflow over forced in-place replacement

Do not squeeze translated text into the original English bounding boxes if that causes collisions with assets.

---

### Source model and rebuild model

The PDF rebuild stage must distinguish between:

- translatable text nodes
- preserved asset nodes
- hybrid nodes with protected spans

During rebuild:
- translated text is retypeset
- preserved assets are reinserted
- structural links are maintained
- page reflow may occur, but object identity must remain stable

This is a controlled reconstruction workflow, not raw text replacement inside the original PDF.

---

### Confidence and fallback behavior

If extraction confidence is low for an image/formula/table region:

- preserve the region as an asset
- record uncertainty
- avoid aggressive reconstruction
- emit a QA or extraction flag if needed

Prefer conservative preservation over visually clean but semantically unsafe reconstruction.

---

### Forbidden behaviors

The system must not:

- translate formula notation as ordinary prose
- rewrite equations for style
- regenerate images from textual description
- silently drop figures, equations, or captions
- detach captions from their assets
- flatten complex tables into free text by default
- change equation numbering
- modify embedded scientific notation without explicit structured support
- pretend successful reconstruction when only weak extraction was available

---

### Preferred v1 policy

For the current project version:

- translate prose, headings, captions, footnotes
- preserve images as assets
- preserve formulas as assets or protected math spans
- preserve tables conservatively
- rebuild the output PDF around those preserved objects

Embedded text inside images, full chart relabeling, formula OCR-to-LaTeX reconstruction, and figure redrawing are future-stage features, not default behavior.