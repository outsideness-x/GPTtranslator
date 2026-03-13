# Review Report

Date: March 13, 2026

## Scope

Repository review and stabilization focused on:

- packaging and console entrypoint
- Linux install flow
- CLI runtime behavior
- prompt asset packaging
- translation backend failure paths
- tests, lint, typing, wheel/install smoke

## Fixed Issues

1. Packaging relied on source-tree prompt files.
   - Problem: prompt templates were resolved via `Path(__file__).parents[4] / "prompts"`, which works from source checkout but breaks after installation from wheel/site-packages.
   - Fix: bundled prompt assets were added under `src/gpttranslator/prompt_assets`, packaged via `pyproject.toml`, and runtime prompt lookup now supports installed layouts.

2. Install flow was not reproducible after clone.
   - Problem: repository assumed an ad hoc in-repo virtualenv (`bin/`, `lib/`, `pyvenv.cfg`) and had no supported install scripts.
   - Fix: added `scripts/install.sh`, `scripts/dev_install.sh`, `scripts/uninstall.sh`, moved `Makefile` to `.venv`-based workflow, and added smoke verification of the generated `gpttranslator` entrypoint.

3. `uv` install path used unwritable/global cache defaults and unnecessary seed-networking.
   - Problem: `uv` could fail in restricted environments and `uv venv --seed` introduced an avoidable network dependency.
   - Fix: install script now uses a local `UV_CACHE_DIR` under the repository and creates the uv venv without `--seed`.

4. `translate` could create workspace/log artifacts for a missing book.
   - Problem: the command wrote `logs/run.log` and Codex log files before validating that the book workspace existed.
   - Fix: workspace existence is now validated before any logging/artifact creation.

5. `translate` could report backend errors before book-data errors.
   - Problem: backend setup happened before chunk/memory validation, so users could get misleading `codex missing` errors even when `extract` had not been run.
   - Fix: translation prerequisites are loaded before backend activation, while still failing fast on missing backend before batch execution.

6. Config metadata was internally inconsistent.
   - Problem: `AppConfig.manifest_filename` said `book_manifest.json`, while the codebase consistently used `manifest.json`.
   - Fix: config now matches actual workspace behavior.

7. Manifest update errors were silently swallowed in `qa` and `build`.
   - Problem: broad `except Exception: pass` masked failures.
   - Fix: defensive manifest writes now log warnings instead of failing silently.

8. Packaging/install regression coverage was missing.
   - Problem: tests only exercised source-tree imports and Typer wiring.
   - Fix: added tests for packaging metadata, bundled prompt-asset parity, missing-book translation failure, and missing-Codex translation failure.

## Verification Performed

Static and automated checks run successfully:

- `./bin/python -m ruff check src tests`
- `./bin/python -m mypy src`
- `./bin/python -m pytest -q`
- `bash -n scripts/install.sh scripts/dev_install.sh scripts/uninstall.sh`

Install and packaging checks run successfully:

- `./scripts/install.sh --venv-dir /tmp/gpttranslator-install-smoke`
- `/tmp/gpttranslator-install-smoke/bin/gpttranslator --help`
- `/tmp/gpttranslator-install-smoke/bin/gpttranslator version`
- `/tmp/gpttranslator-install-smoke/bin/gpttranslator status` in a clean temp directory
- `python3 -m pip wheel . --no-build-isolation --no-deps -w /tmp/gpttranslator-dist`

Installed-CLI runtime smoke run successfully in `/tmp/gpttranslator-cli-e2e.WeHBZJ`:

- `gpttranslator init`
- `gpttranslator inspect`
- `gpttranslator extract`
- `gpttranslator glossary`
- `gpttranslator translate --backend mock --profile balanced --batch-size 2 --strict-json`
- `gpttranslator qa --local-only`
- `gpttranslator build`
- `gpttranslator status <book_id>`

Missing-Codex failure behavior verified manually in `/tmp/gpttranslator-no-codex.jYduDy`:

- `GPTTRANSLATOR_CODEX_COMMAND=codex-does-not-exist gpttranslator translate <book_id> --backend codex-cli`
- Result: clear failure message, exit code 1, and no `jobs/` directory created.

Wheel contents verified:

- `gpttranslator-0.1.0-py3-none-any.whl` contains `gpttranslator/prompt_assets/*`
- wheel also contains `entry_points.txt` for the `gpttranslator` console script

## Remaining Limitations

- Real end-to-end translation with an actual `codex` binary was not executed in this environment because the goal of this stabilization pass was installability and deterministic/mock verification first.
- Initial dependency installation still requires package index access unless the local cache already contains the needed wheels.
- Build output for complex PDFs still depends on controlled reflow heuristics and can legitimately emit warnings.
- No global/system-wide installation flow was added; the supported path is virtualenv activation plus the generated console script.

## Deferred / Not Changed

- No Dockerization was added.
- No network translation backend or API integration was introduced.
- No broad architectural refactor was done beyond install/runtime stabilization.

## Current Assessment

The repository is now in a state where it can be cloned, installed into a fresh virtual environment, invoked via `gpttranslator`, smoke-tested locally, and exercised through a full mock pipeline without depending on the source tree layout for prompt assets.
