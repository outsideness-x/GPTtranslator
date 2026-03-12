# GPTtranslator Prompt Template: Terminology Check

- Prompt schema version: `{{prompt_schema_version}}`
- Template id: `{{template_id}}`
- Template version: `{{template_version}}`
- Job id: `{{job_id}}`

## Objective

Verify terminology consistency against glossary and style guidance for the chunk.

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

1. Preserve all footnote markers exactly.
2. Preserve `chunk_id` and `block_ids` exactly.
3. Report only terminology-related findings.
4. Do not rewrite text unless required by output contract.
5. Output MUST be strict JSON matching the schema below.
6. Write JSON only to `{{output_json_path}}`.
7. Do not emit free-form text outside the JSON contract.

## Output JSON Schema (`{{output_schema_version}}`)

```json
{{output_schema_json}}
```

## Output JSON Skeleton

```json
{{output_skeleton_json}}
```
