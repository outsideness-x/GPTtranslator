#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/install.sh [--dev] [--python <python-bin>] [--venv-dir <path>]

Installs GPTtranslator into a local virtual environment.

Options:
  --dev               Install development dependencies too.
  --python <bin>      Python interpreter to use. Default: python3
  --venv-dir <path>   Virtualenv path. Default: .venv in the repository root
  -h, --help          Show this help message.
EOF
}

die() {
  local code="$1"
  shift
  printf 'install.sh: %s\n' "$*" >&2
  exit "$code"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${GPTTRANSLATOR_PYTHON:-python3}"
VENV_DIR="${GPTTRANSLATOR_VENV_DIR:-${PROJECT_ROOT}/.venv}"
UV_CACHE_DIR="${UV_CACHE_DIR:-${PROJECT_ROOT}/.uv-cache}"
INSTALL_DEV=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev)
      INSTALL_DEV=1
      shift
      ;;
    --python)
      [[ $# -ge 2 ]] || die 64 "--python requires a value"
      PYTHON_BIN="$2"
      shift 2
      ;;
    --venv-dir)
      [[ $# -ge 2 ]] || die 64 "--venv-dir requires a value"
      VENV_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die 64 "unknown argument: $1"
      ;;
  esac
done

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die 2 "python interpreter not found: $PYTHON_BIN"

"$PYTHON_BIN" - <<'PY' || die 2 "Python 3.11+ is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

mkdir -p "$(dirname "$VENV_DIR")"

printf 'Project root: %s\n' "$PROJECT_ROOT"
printf 'Virtualenv  : %s\n' "$VENV_DIR"
printf 'Python      : %s\n' "$PYTHON_BIN"

if command -v uv >/dev/null 2>&1; then
  export UV_CACHE_DIR
  mkdir -p "$UV_CACHE_DIR"
  printf 'Installer   : uv\n'
  printf 'uv cache    : %s\n' "$UV_CACHE_DIR"
  uv venv --allow-existing --python "$PYTHON_BIN" "$VENV_DIR" || die 3 "failed to create virtualenv with uv"
  UV_INSTALL_ARGS=(
    uv pip install
    --python "$VENV_DIR/bin/python"
    --editable "$PROJECT_ROOT"
  )
  if [[ "$INSTALL_DEV" -eq 1 ]]; then
    UV_INSTALL_ARGS+=(--extra dev)
  fi
  "${UV_INSTALL_ARGS[@]}" || die 3 "dependency installation failed"
else
  printf 'Installer   : python -m venv + pip\n'
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR" || die 3 "failed to create virtualenv"
  fi
  "$VENV_DIR/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel || die 3 "failed to bootstrap pip/setuptools/wheel"
  INSTALL_TARGET="$PROJECT_ROOT"
  if [[ "$INSTALL_DEV" -eq 1 ]]; then
    INSTALL_TARGET="${PROJECT_ROOT}[dev]"
  fi
  "$VENV_DIR/bin/python" -m pip install --no-build-isolation --editable "$INSTALL_TARGET" || die 3 "editable install failed"
fi

[[ -x "$VENV_DIR/bin/gpttranslator" ]] || die 4 "console script was not created: $VENV_DIR/bin/gpttranslator"
"$VENV_DIR/bin/gpttranslator" --help >/dev/null || die 4 "installed gpttranslator failed its help smoke test"

printf '\nInstallation complete.\n'
printf 'Activate the environment:\n'
printf '  source "%s/bin/activate"\n' "$VENV_DIR"
printf 'Then run:\n'
printf '  gpttranslator --help\n'
printf '  gpttranslator version\n'
printf '  gpttranslator status\n'
