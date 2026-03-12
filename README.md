# GPTtranslate

Minimalist terminal CLI shell for the `GPTtranslate` project.

## Scope of this stage

- No translation runtime yet.
- No API integrations.
- No PDF pipeline.
- Commands are scaffolded to define stable CLI UX.

## Install (editable)

```bash
python -m pip install -e .[dev]
```

## Run

```bash
gpttranslator --help
gpttranslator status
gpttranslator version
```

## Commands

- `help`
- `status`
- `init`
- `inspect`
- `extract`
- `glossary`
- `translate`
- `qa`
- `build`
- `version`

## Tests

```bash
pytest
```
