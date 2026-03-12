# GPTtranslator Codex Job

- Prompt schema version: `gpttranslator.codex.prompt_template.v1`
- Template id: `translate_chunk_v1`
- Template version: `1`
- Job id: `job-0001`

## Task

1. Read the input JSON file at `/tmp/demo-book/jobs/job-0001/input.json`.
2. Translate `payload.source_text` according to glossary and style hints.
3. Write exactly one JSON object to `/tmp/demo-book/jobs/job-0001/output.json`.
4. Do not print translation result to stdout or stderr.
5. The JSON in output.json must match schema `gpttranslator.codex.output.v1`.
