# Prompts

Production prompt templates for file-based Codex jobs.

## Template Catalog

- `translate_chunk.prompt.md`
  - Stage: `translate`
  - Purpose: primary chunk translation with strict structure preservation.
- `editorial_pass.prompt.md`
  - Stage: `translate` (post-pass for selected risky chunks)
  - Purpose: improve fluency/style without semantic drift.
- `terminology_check.prompt.md`
  - Stage: `qa`
  - Purpose: validate glossary and term consistency.
- `semantic_qa.prompt.md`
  - Stage: `qa`
  - Purpose: detect semantic drift, omissions, and additions.
- `chapter_summary.prompt.md`
  - Stage: `memory` / chapter-level analysis
  - Purpose: generate chapter summary artifacts with explicit chunk/block references.
- `glossary_update_proposal.prompt.md`
  - Stage: `glossary`
  - Purpose: propose glossary updates grounded in chapter evidence.

## Rendering

Templates are rendered through `gpttranslator.app.translation.protocol.render_prompt()`.

Placeholders are resolved from prompt payload and template-specific output schema:

- `{{input_json_path}}`
- `{{output_json_path}}`
- `{{output_schema_json}}`
- `{{output_skeleton_json}}`

All templates enforce strict JSON output to `output.json` and disallow free-form text outside output schema.
