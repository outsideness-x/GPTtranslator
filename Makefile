PYTHON ?= ./bin/python
PIP ?= ./bin/pip

.PHONY: dev-install test test-smoke lint format format-check typecheck check ci

dev-install:
	$(PIP) install -e '.[dev]'

test:
	$(PYTHON) -m pytest -q

test-smoke:
	$(PYTHON) -m pytest -q tests/test_cli_smoke.py tests/test_integration_smoke_pipeline.py

lint:
	$(PYTHON) -m ruff check src tests

format:
	$(PYTHON) -m ruff format src tests

format-check:
	$(PYTHON) -m ruff format --check src tests

typecheck:
	$(PYTHON) -m mypy src

check: lint typecheck test

ci: format-check lint typecheck test
