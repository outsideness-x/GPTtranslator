#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${GPTTRANSLATOR_VENV_DIR:-${PROJECT_ROOT}/.venv}"
EGG_INFO_DIR="${PROJECT_ROOT}/src/gpttranslator.egg-info"

if [[ ! -e "$VENV_DIR" && ! -e "$EGG_INFO_DIR" ]]; then
  printf 'Nothing to uninstall.\n'
  exit 0
fi

if [[ -e "$VENV_DIR" ]]; then
  rm -rf "$VENV_DIR"
  printf 'Removed virtualenv: %s\n' "$VENV_DIR"
fi

if [[ -e "$EGG_INFO_DIR" ]]; then
  rm -rf "$EGG_INFO_DIR"
  printf 'Removed editable-install metadata: %s\n' "$EGG_INFO_DIR"
fi

printf 'Uninstall complete.\n'
