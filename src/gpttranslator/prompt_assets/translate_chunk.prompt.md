# GPTtranslator Prompt Template: Translate Chunk

- Prompt schema version: `{{prompt_schema_version}}`
- Template id: `{{template_id}}`
- Template version: `{{template_version}}`
- Job id: `{{job_id}}`

## Objective

Translate one source chunk from `input.json` into high-quality Russian while preserving structure-critical markers.

## Input Source

- Read input JSON only from: `{{input_json_path}}`
- Use and respect:
  - `payload.glossary`
  - `payload.style_guide`
  - `payload.chapter_notes`
  - `payload.style_hints`
  - `payload.chunk_id`
  - `payload.block_ids`
  - `payload.footnote_markers`

## Hard Constraints

1. Preserve all footnote markers exactly as they appear in source content.
2. Preserve identity fields exactly:
   - `chunk_id`
   - `block_ids`
3. Do not invent new facts and do not omit meaning.
4. Output MUST be strict JSON matching the schema below.
5. Write JSON only to `{{output_json_path}}`.
6. Do not emit free-form text outside the JSON contract.
7. Do not print translated text to stdout or stderr.

## Output JSON Schema (`{{output_schema_version}}`)

```json
{{output_schema_json}}
```

## Output JSON Skeleton

```json
{{output_skeleton_json}}
```
