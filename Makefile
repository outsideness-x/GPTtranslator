VENV_DIR ?= .venv
PYTHON ?= $(VENV_DIR)/bin/python
PIP ?= $(VENV_DIR)/bin/pip
CLI ?= $(VENV_DIR)/bin/gpttranslator

.PHONY: install dev-install test lint format format-check typecheck smoke check ci

install:
	./scripts/install.sh

dev-install:
	./scripts/dev_install.sh

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src tests

format:
	$(PYTHON) -m ruff format src tests

format-check:
	$(PYTHON) -m ruff format --check src tests

typecheck:
	$(PYTHON) -m mypy src

smoke:
	$(CLI) --help
	$(CLI) version
	$(CLI) status

check: lint typecheck test

ci: format-check lint typecheck test
