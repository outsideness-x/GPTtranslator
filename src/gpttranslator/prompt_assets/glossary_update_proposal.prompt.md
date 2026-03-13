# GPTtranslator Prompt Template: Glossary Update Proposal

- Prompt schema version: `{{prompt_schema_version}}`
- Template id: `{{template_id}}`
- Template version: `{{template_version}}`
- Job id: `{{job_id}}`

## Objective

Propose glossary updates based on chapter evidence and style constraints.

## Input Source

- Read input JSON only from: `{{input_json_path}}`
- Use and respect:
  - `payload.glossary`
  - `payload.style_guide`
  - `payload.chapter_notes`
  - `payload.style_hints`
  - `payload.chapter_id`
  - `payload.chunk_ids`
  - `payload.block_ids`
  - `payload.footnote_markers`

## Hard Constraints

1. Preserve all listed footnote markers exactly.
2. Preserve `chapter_id`, `chunk_ids`, and `block_ids` exactly.
3. Every proposal must include rationale and evidence chunk IDs.
4. Output MUST be strict JSON matching the schema below.
5. Write JSON only to `{{output_json_path}}`.
6. Do not emit free-form text outside the JSON contract.

## Output JSON Schema (`{{output_schema_version}}`)

```json
{{output_schema_json}}
```

## Output JSON Skeleton

```json
{{output_skeleton_json}}
```
