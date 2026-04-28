#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"

have_command() {
  command -v "$1" >/dev/null 2>&1
}

run_with_optional_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif have_command sudo; then
    sudo "$@"
  else
    "$@"
  fi
}

check_python_version() {
  "$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(
        f"Python 3.10+ is required. Found {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}."
    )
PY
}

install_system_packages() {
  if have_command apt-get; then
    run_with_optional_sudo apt-get update
    run_with_optional_sudo apt-get install -y python3-venv tesseract-ocr
    return
  fi

  echo "Unsupported package manager. Install these manually, then rerun this script:" >&2
  echo "  - Python 3.10+" >&2
  echo "  - python3-venv (or equivalent venv support)" >&2
  echo "  - tesseract-ocr" >&2
  exit 1
}

show_disk_state() {
  echo "Filesystem state:"
  df -h "$ROOT_DIR"
  echo
}

main() {
  cd "$ROOT_DIR"

  echo "Checking disk availability..."
  show_disk_state

  if ! have_command "$PYTHON_BIN"; then
    echo "Missing $PYTHON_BIN. Install Python 3.10+ first." >&2
    exit 1
  fi

  echo "Checking Python version..."
  check_python_version

  if ! have_command tesseract; then
    echo "Tesseract not found. Installing system packages..."
    install_system_packages
  else
    echo "Tesseract already installed: $(command -v tesseract)"
  fi

  if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  else
    echo "Using existing virtual environment at $VENV_DIR"
  fi

  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"

  echo "Upgrading pip..."
  pip install --upgrade pip

  echo "Installing Python dependencies..."
  pip install -r "$ROOT_DIR/requirements-ocr.txt"

  echo
  echo "Environment ready."
  echo "Activate it with:"
  echo "  source \"$VENV_DIR/bin/activate\""
}

main "$@"
